/*
 * ALSA playback device of the emulator's "audio" driver feature, for the
 * strategies in which the target has no sound hardware of its own.
 *
 * It is an ALSA external PCM plugin ("type emu" in /etc/asound.conf, written
 * by /opt/emu/drivers/audio). To target software it is a sound card: it
 * accepts 16-bit stereo at 48 kHz, plays it at exactly that rate, reports
 * its position and under-runs, and can be waited on. What it does with the
 * samples it plays is the strategy's choice:
 *
 *   server "HOST:PORT"   send them to the launcher's host-side audio process,
 *                        which plays them through the host OS (strategy host)
 *   no server            discard them (the software model of a sound card,
 *                        and the mocked device)
 *
 * Samples leave the device when it plays them, not when the player writes
 * them: a player may fill a buffer of several seconds, and what the host
 * plays, or mutes, has to be what the target is playing now. A thread of the
 * device does that, so it does not depend on when the player calls ALSA.
 *
 * The device never blocks the player on the network for long: when the
 * host-side process cannot be reached or goes away, it keeps playing to
 * nowhere.
 *
 * Build: gcc -shared -fPIC -DPIC -o libasound_module_pcm_emu.so emu_alsa.c -lasound -lpthread
 */
#define _GNU_SOURCE

#include <errno.h>
#include <netdb.h>
#include <poll.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/timerfd.h>
#include <time.h>
#include <unistd.h>

#include <alsa/asoundlib.h>
#include <alsa/pcm_external.h>

#define EMU_RATE 48000
#define EMU_CHANNELS 2
#define EMU_FRAME_BYTES 4
#define EMU_TICK_NS 5000000             /* how often the device looks at its clock */
#define EMU_LEAD_FRAMES (EMU_RATE / 50) /* sent this far ahead of the clock, to cover a late tick */

struct emu {
    snd_pcm_ioplug_t io;
    int timer; /* what a waiting player polls */
    int sock;  /* connection to the host-side process, or -1 */
    pthread_t thread;
    pthread_mutex_t lock;
    int quit;
    int ready; /* the buffer exists: between prepare and hw_free */
    int running;
    uint64_t start_ns;
    uint64_t played;            /* frames played before the device last stopped */
    uint64_t written;           /* frames the player has written since the stream was prepared */
    uint64_t sent;              /* frames passed on (or discarded) since then */
    snd_pcm_uframes_t seen;     /* the player's write position when `written` was last brought up to date */
    snd_pcm_uframes_t boundary; /* where ALSA wraps that position */
};

static uint64_t now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static void arm_timer(struct emu *emu, long interval_ns)
{
    struct itimerspec spec = {{0, interval_ns}, {0, interval_ns}};
    timerfd_settime(emu->timer, 0, &spec, NULL);
}

static void emu_send(struct emu *emu, const char *data, size_t left)
{
    while (emu->sock >= 0 && left > 0) {
        ssize_t sent = send(emu->sock, data, left, MSG_NOSIGNAL);
        if (sent <= 0) {
            if (sent < 0 && errno == EINTR)
                continue;
            close(emu->sock); /* the host side is gone; keep playing to nowhere */
            emu->sock = -1;
            break;
        }
        data += sent;
        left -= (size_t)sent;
    }
}

/* Frames the device's clock says it has played, whether or not it had them. */
static uint64_t emu_clock(struct emu *emu)
{
    uint64_t played = emu->played;
    if (emu->running)
        played += (now_ns() - emu->start_ns) * EMU_RATE / 1000000000ull;
    return played;
}

/* Bring the device up to date. Called with the lock held, by the device's
 * thread and whenever the player asks for the position.
 *
 * Players write in different ways (plain writes, or through ALSA's converters
 * straight into the buffer); the buffer is where all of them end up, so the
 * device reads its samples from there. Frame n since the stream was prepared
 * sits at n modulo the buffer size until the player overwrites it, which it
 * cannot do before the device has played it. */
static void emu_update(struct emu *emu)
{
    snd_pcm_ioplug_t *io = &emu->io;
    const snd_pcm_channel_area_t *areas;
    snd_pcm_uframes_t appl, fresh, offset, chunk;
    uint64_t due;

    if (!emu->ready)
        return;
    appl = io->appl_ptr;
    fresh = appl >= emu->seen ? appl - emu->seen : emu->boundary - emu->seen + appl;
    if (fresh <= io->buffer_size)
        emu->written += fresh;
    emu->seen = appl;

    due = emu_clock(emu) + (emu->running ? EMU_LEAD_FRAMES : 0);
    if (due > emu->written)
        due = emu->written;
    areas = snd_pcm_ioplug_mmap_areas(io);
    while (emu->sent < due) {
        offset = (snd_pcm_uframes_t)(emu->sent % io->buffer_size);
        chunk = io->buffer_size - offset;
        if (chunk > due - emu->sent)
            chunk = (snd_pcm_uframes_t)(due - emu->sent);
        if (areas)
            emu_send(emu, (const char *)areas->addr + (areas->first + areas->step * offset) / 8,
                     chunk * EMU_FRAME_BYTES);
        emu->sent += chunk;
    }
}

static void *emu_thread(void *data)
{
    struct emu *emu = data;
    struct timespec tick = {0, EMU_TICK_NS};

    for (;;) {
        nanosleep(&tick, NULL);
        pthread_mutex_lock(&emu->lock);
        if (emu->quit) {
            pthread_mutex_unlock(&emu->lock);
            return NULL;
        }
        if (emu->running)
            emu_update(emu);
        pthread_mutex_unlock(&emu->lock);
    }
}

static int emu_prepare(snd_pcm_ioplug_t *io)
{
    struct emu *emu = io->private_data;
    snd_pcm_sw_params_t *sw;
    snd_pcm_uframes_t boundary = 0;

    snd_pcm_sw_params_alloca(&sw);
    if (snd_pcm_sw_params_current(io->pcm, sw) < 0 || snd_pcm_sw_params_get_boundary(sw, &boundary) < 0)
        boundary = 0;
    pthread_mutex_lock(&emu->lock);
    emu->running = 0;
    emu->played = emu->written = emu->sent = 0;
    emu->seen = 0;
    emu->boundary = boundary;
    emu->ready = 1;
    pthread_mutex_unlock(&emu->lock);
    /* Readable at once: a prepared device has room for samples. */
    arm_timer(emu, 1);
    return 0;
}

static int emu_start(snd_pcm_ioplug_t *io)
{
    struct emu *emu = io->private_data;
    pthread_mutex_lock(&emu->lock);
    emu->start_ns = now_ns();
    emu->running = 1;
    pthread_mutex_unlock(&emu->lock);
    arm_timer(emu, EMU_TICK_NS);
    return 0;
}

static int emu_stop(snd_pcm_ioplug_t *io)
{
    struct emu *emu = io->private_data;
    uint64_t played;

    pthread_mutex_lock(&emu->lock);
    emu_update(emu);
    played = emu_clock(emu);
    /* A stopped device stands still: what it was given waits in its buffer. */
    emu->played = played < emu->written ? played : emu->written;
    emu->running = 0;
    pthread_mutex_unlock(&emu->lock);
    return 0;
}

static int emu_hw_free(snd_pcm_ioplug_t *io)
{
    struct emu *emu = io->private_data;
    pthread_mutex_lock(&emu->lock);
    emu->running = 0;
    emu->ready = 0; /* the buffer goes away */
    pthread_mutex_unlock(&emu->lock);
    return 0;
}

/* The position of the device: the frames it has played. It plays what it was
 * given at the sample rate; with nothing left to play it has under-run. */
static snd_pcm_sframes_t emu_pointer(snd_pcm_ioplug_t *io)
{
    struct emu *emu = io->private_data;
    uint64_t played, written;

    pthread_mutex_lock(&emu->lock);
    emu_update(emu);
    played = emu_clock(emu);
    written = emu->written;
    pthread_mutex_unlock(&emu->lock);
    if (played > written) {
        if (io->state != SND_PCM_STATE_DRAINING && played > written + io->period_size)
            return -EPIPE;
        played = written;
    }
    return (snd_pcm_sframes_t)(played % io->buffer_size);
}

static int emu_poll_revents(snd_pcm_ioplug_t *io, struct pollfd *pfd, unsigned int nfds, unsigned short *revents)
{
    struct emu *emu = io->private_data;
    uint64_t ticks;
    snd_pcm_sframes_t avail;

    (void)nfds;
    *revents = 0;
    if (pfd[0].revents & POLLIN) {
        if (read(emu->timer, &ticks, sizeof ticks) < 0 && errno != EAGAIN)
            return -errno;
        avail = snd_pcm_avail_update(io->pcm);
        if (avail < 0)
            *revents = POLLOUT | POLLERR; /* under-run: let the player see it */
        else if ((snd_pcm_uframes_t)avail >= io->period_size)
            *revents = POLLOUT;
    }
    return 0;
}

static void emu_destroy(struct emu *emu)
{
    pthread_mutex_lock(&emu->lock);
    emu->quit = 1;
    emu->ready = 0;
    pthread_mutex_unlock(&emu->lock);
    pthread_join(emu->thread, NULL);
    if (emu->sock >= 0)
        close(emu->sock);
    close(emu->timer);
    pthread_mutex_destroy(&emu->lock);
    free(emu);
}

static int emu_close(snd_pcm_ioplug_t *io)
{
    emu_destroy(io->private_data);
    return 0;
}

static const snd_pcm_ioplug_callback_t emu_callbacks = {
    .start = emu_start,
    .stop = emu_stop,
    .pointer = emu_pointer,
    .prepare = emu_prepare,
    .hw_free = emu_hw_free,
    .poll_revents = emu_poll_revents,
    .close = emu_close,
};

static int emu_connect(const char *server)
{
    char host[256];
    const char *colon = strrchr(server, ':');
    struct addrinfo hints = {.ai_socktype = SOCK_STREAM}, *found, *item;
    struct timeval limit = {2, 0};
    static const char hello[] = "EMU-PCM s16le 48000 2\n";
    int sock = -1;

    if (!colon || (size_t)(colon - server) >= sizeof host)
        return -1;
    memcpy(host, server, (size_t)(colon - server));
    host[colon - server] = '\0';
    if (getaddrinfo(host, colon + 1, &hints, &found) != 0)
        return -1;
    for (item = found; item; item = item->ai_next) {
        sock = socket(item->ai_family, item->ai_socktype | SOCK_CLOEXEC, item->ai_protocol);
        if (sock < 0)
            continue;
        setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &limit, sizeof limit);
        if (connect(sock, item->ai_addr, item->ai_addrlen) == 0 &&
            send(sock, hello, sizeof hello - 1, MSG_NOSIGNAL) == (ssize_t)(sizeof hello - 1))
            break;
        close(sock);
        sock = -1;
    }
    freeaddrinfo(found);
    return sock;
}

static int emu_constrain(struct emu *emu)
{
    /* Memory-mapped access as well: ALSA's rate converter only talks to its
     * device that way. */
    static const unsigned int accesses[] = {SND_PCM_ACCESS_MMAP_INTERLEAVED, SND_PCM_ACCESS_RW_INTERLEAVED};
    static const unsigned int formats[] = {SND_PCM_FORMAT_S16_LE};
    snd_pcm_ioplug_t *io = &emu->io;
    int err;

    if ((err = snd_pcm_ioplug_set_param_list(io, SND_PCM_IOPLUG_HW_ACCESS, 2, accesses)) < 0 ||
        (err = snd_pcm_ioplug_set_param_list(io, SND_PCM_IOPLUG_HW_FORMAT, 1, formats)) < 0 ||
        (err = snd_pcm_ioplug_set_param_minmax(io, SND_PCM_IOPLUG_HW_CHANNELS, EMU_CHANNELS, EMU_CHANNELS)) < 0 ||
        (err = snd_pcm_ioplug_set_param_minmax(io, SND_PCM_IOPLUG_HW_RATE, EMU_RATE, EMU_RATE)) < 0 ||
        /* wide enough for any player: buffers of a few milliseconds up to ten seconds */
        (err = snd_pcm_ioplug_set_param_minmax(io, SND_PCM_IOPLUG_HW_PERIOD_BYTES, 128, 1 << 20)) < 0 ||
        (err = snd_pcm_ioplug_set_param_minmax(io, SND_PCM_IOPLUG_HW_PERIODS, 2, 1024)) < 0 ||
        (err = snd_pcm_ioplug_set_param_minmax(io, SND_PCM_IOPLUG_HW_BUFFER_BYTES, 256, 1920000)) < 0)
        return err;
    return 0;
}

SND_PCM_PLUGIN_DEFINE_FUNC(emu)
{
    snd_config_iterator_t i, next;
    const char *server = NULL;
    struct emu *emu;
    int err;

    (void)root;
    snd_config_for_each(i, next, conf) {
        snd_config_t *n = snd_config_iterator_entry(i);
        const char *id;
        if (snd_config_get_id(n, &id) < 0)
            continue;
        if (!strcmp(id, "comment") || !strcmp(id, "type") || !strcmp(id, "hint"))
            continue;
        if (!strcmp(id, "server")) {
            if (snd_config_get_string(n, &server) < 0) {
                SNDERR("emu: server must be a string, HOST:PORT");
                return -EINVAL;
            }
            continue;
        }
        SNDERR("emu: unknown field %s", id);
        return -EINVAL;
    }
    if (stream != SND_PCM_STREAM_PLAYBACK) {
        SNDERR("emu: the device only plays");
        return -EINVAL;
    }

    emu = calloc(1, sizeof *emu);
    if (!emu)
        return -ENOMEM;
    emu->timer = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
    if (emu->timer < 0) {
        err = -errno;
        free(emu);
        return err;
    }
    emu->sock = server && *server ? emu_connect(server) : -1;
    pthread_mutex_init(&emu->lock, NULL);
    if ((err = pthread_create(&emu->thread, NULL, emu_thread, emu)) != 0) {
        if (emu->sock >= 0)
            close(emu->sock);
        close(emu->timer);
        pthread_mutex_destroy(&emu->lock);
        free(emu);
        return -err;
    }
    emu->io.version = SND_PCM_IOPLUG_VERSION;
    emu->io.name = "Emulator audio device";
    emu->io.callback = &emu_callbacks;
    emu->io.private_data = emu;
    emu->io.poll_fd = emu->timer;
    emu->io.poll_events = POLLIN;
    /* The device reads the buffer itself (see emu_update). */
    emu->io.mmap_rw = 1;
    if ((err = snd_pcm_ioplug_create(&emu->io, name, stream, mode)) < 0) {
        emu_destroy(emu);
        return err;
    }
    if ((err = emu_constrain(emu)) < 0) {
        snd_pcm_ioplug_delete(&emu->io); /* closes the device, which frees it */
        return err;
    }
    *pcmp = emu->io.pcm;
    return 0;
}

SND_PCM_PLUGIN_SYMBOL(emu);
