/*
 * emuscreen: serves the target's display to the launcher's window.
 *
 *     emuscreen --port PORT
 *
 * For container mode, where the compositor draws to an output that no
 * emulator shows (in VM mode the emulator serves its own display device).
 * emuscreen is a client of the compositor that captures the output, one frame
 * after another (Weston's output capture protocol, the one its screenshot
 * program uses), and a server of the remote framebuffer protocol (RFB, the
 * protocol of VNC) for one viewer at a time on a TCP port.
 *
 * As little of RFB as the launcher's viewer needs: protocol 3.8, no
 * authentication, pixels as the compositor has them (four bytes: blue, green,
 * red, unused), raw encoding. A viewer asks for an update and gets the rows
 * that changed since the last one it was sent. Key and pointer messages are
 * read and dropped: remote control keys reach the compositor another way
 * (emu_remote.c).
 *
 * Capturing asks the compositor to repaint, so frames come at most at the
 * output's refresh rate. While nothing on the display changes, emuscreen
 * looks less often.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include <wayland-client.h>

#include "weston-output-capture-client-protocol.h"

#define DRM_FORMAT_XRGB8888 0x34325258
#define DRM_FORMAT_ARGB8888 0x34325241
/* After this many captures without a change, the next ones are this far apart. */
#define QUIET_CAPTURES 30
#define QUIET_INTERVAL_MS 100

struct screen {
    struct wl_display *display;
    struct wl_shm *shm;
    struct wl_output *output;
    struct weston_capture_v1 *factory;
    struct weston_capture_source_v1 *source;
    uint32_t format;                /* DRM format the compositor captures in */
    int width, height;              /* size it captures in */

    struct wl_buffer *buffer;       /* what a capture is written into */
    uint8_t *pixels;
    int buffer_width, buffer_height;
    uint8_t *sent;                  /* what the viewer has been sent */
    bool capturing;                 /* a capture is under way */
    bool captured;                  /* one has completed since the last look */
    bool failed;

    int viewer;                     /* the viewer's connection, or -1 */
    bool greeted;                   /* past the opening exchange */
    bool wants;                     /* the viewer has asked for an update */
    bool everything;                /* and for all of the display, not the changes */
    int unchanged;                  /* captures in a row that showed nothing new */
    int64_t not_before;             /* when the next capture may start, in milliseconds */
};

static int64_t now_ms(void)
{
    struct timespec now;

    clock_gettime(CLOCK_MONOTONIC, &now);
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

/* ------------------------------------------------------------ capture --- */

static void release_buffer(struct screen *screen)
{
    if (screen->buffer)
        wl_buffer_destroy(screen->buffer);
    if (screen->pixels)
        munmap(screen->pixels, (size_t)screen->buffer_width * screen->buffer_height * 4);
    free(screen->sent);
    screen->buffer = NULL;
    screen->pixels = NULL;
    screen->sent = NULL;
}

static bool make_buffer(struct screen *screen)
{
    size_t size = (size_t)screen->width * screen->height * 4;
    struct wl_shm_pool *pool;
    int fd;

    release_buffer(screen);
    if (screen->format != DRM_FORMAT_XRGB8888 && screen->format != DRM_FORMAT_ARGB8888) {
        fprintf(stderr, "emuscreen: the compositor captures in a pixel format this program does not serve (0x%08x)\n",
                screen->format);
        return false;
    }
    fd = memfd_create("emuscreen", MFD_CLOEXEC);
    if (fd < 0 || ftruncate(fd, (off_t)size) < 0) {
        perror("emuscreen: memory for the capture");
        return false;
    }
    screen->pixels = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    screen->sent = calloc(1, size);
    if (screen->pixels == MAP_FAILED || !screen->sent) {
        perror("emuscreen: memory for the capture");
        screen->pixels = NULL;
        close(fd);
        return false;
    }
    pool = wl_shm_create_pool(screen->shm, fd, (int32_t)size);
    /* wl_shm names these two formats 1 and 0. */
    screen->buffer = wl_shm_pool_create_buffer(pool, 0, screen->width, screen->height, screen->width * 4,
                                               screen->format == DRM_FORMAT_XRGB8888 ? WL_SHM_FORMAT_XRGB8888
                                                                                     : WL_SHM_FORMAT_ARGB8888);
    wl_shm_pool_destroy(pool);
    close(fd);
    screen->buffer_width = screen->width;
    screen->buffer_height = screen->height;
    return true;
}

static void on_format(void *data, struct weston_capture_source_v1 *source, uint32_t format)
{
    struct screen *screen = data;
    (void)source;
    screen->format = format;
}

static void on_size(void *data, struct weston_capture_source_v1 *source, int32_t width, int32_t height)
{
    struct screen *screen = data;
    (void)source;
    screen->width = width;
    screen->height = height;
}

static void on_complete(void *data, struct weston_capture_source_v1 *source)
{
    struct screen *screen = data;
    (void)source;
    screen->capturing = false;
    screen->captured = true;
}

static void on_retry(void *data, struct weston_capture_source_v1 *source)
{
    struct screen *screen = data;
    (void)source;
    screen->capturing = false;      /* the size or format changed: the next capture makes a new buffer */
}

static void on_failed(void *data, struct weston_capture_source_v1 *source, const char *message)
{
    struct screen *screen = data;
    (void)source;
    fprintf(stderr, "emuscreen: the compositor did not capture its output: %s\n", message ? message : "no reason given");
    screen->capturing = false;
    screen->failed = true;
}

static const struct weston_capture_source_v1_listener source_listener = {
    .format = on_format, .size = on_size, .complete = on_complete, .retry = on_retry, .failed = on_failed,
};

static void on_global(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
    struct screen *screen = data;
    (void)version;
    if (strcmp(interface, wl_shm_interface.name) == 0)
        screen->shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
    else if (strcmp(interface, wl_output_interface.name) == 0 && !screen->output)
        screen->output = wl_registry_bind(registry, name, &wl_output_interface, 1);
    else if (strcmp(interface, weston_capture_v1_interface.name) == 0)
        screen->factory = wl_registry_bind(registry, name, &weston_capture_v1_interface, 1);
}

static void on_global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
    (void)data;
    (void)registry;
    (void)name;
}

static const struct wl_registry_listener registry_listener = { on_global, on_global_remove };

static void capture(struct screen *screen)
{
    if (screen->capturing || screen->failed || screen->width <= 0)
        return;
    if (!screen->buffer || screen->buffer_width != screen->width || screen->buffer_height != screen->height) {
        if (!make_buffer(screen)) {
            screen->failed = true;
            return;
        }
        screen->everything = true;
    }
    weston_capture_source_v1_capture(screen->source, screen->buffer);
    screen->capturing = true;
}

/* ------------------------------------------------------------- viewer --- */

static void drop_viewer(struct screen *screen)
{
    if (screen->viewer >= 0)
        close(screen->viewer);
    screen->viewer = -1;
    screen->greeted = screen->wants = screen->everything = false;
}

static bool send_all(struct screen *screen, const void *data, size_t count)
{
    const uint8_t *bytes = data;

    while (count > 0) {
        ssize_t sent = send(screen->viewer, bytes, count, MSG_NOSIGNAL);
        if (sent < 0 && errno == EINTR)
            continue;
        if (sent <= 0) {
            drop_viewer(screen);
            return false;
        }
        bytes += sent;
        count -= (size_t)sent;
    }
    return true;
}

static bool receive_all(struct screen *screen, void *data, size_t count)
{
    uint8_t *bytes = data;

    while (count > 0) {
        ssize_t got = recv(screen->viewer, bytes, count, 0);
        if (got < 0 && errno == EINTR)
            continue;
        if (got <= 0) {
            drop_viewer(screen);
            return false;
        }
        bytes += got;
        count -= (size_t)got;
    }
    return true;
}

static void put16(uint8_t *at, unsigned value)
{
    at[0] = (uint8_t)(value >> 8);
    at[1] = (uint8_t)value;
}

/* The opening exchange of RFB 3.8, with a viewer that has just connected. */
static void greet(struct screen *screen)
{
    static const char name[] = "emu-target";
    uint8_t in[16], init[24 + sizeof name - 1] = { 0 };

    if (!send_all(screen, "RFB 003.008\n", 12) || !receive_all(screen, in, 12))
        return;
    if (!send_all(screen, "\x01\x01", 2) || !receive_all(screen, in, 1))        /* one security type: none */
        return;
    if (!send_all(screen, "\0\0\0\0", 4) || !receive_all(screen, in, 1))        /* accepted; then the viewer's "shared" flag */
        return;
    put16(init, (unsigned)screen->width);
    put16(init + 2, (unsigned)screen->height);
    init[4] = 32;               /* bits per pixel */
    init[5] = 24;               /* of which colour */
    init[6] = 0;                /* least significant byte first */
    init[7] = 1;                /* true colour */
    put16(init + 8, 255);
    put16(init + 10, 255);
    put16(init + 12, 255);
    init[14] = 16;              /* red, green and blue shifts */
    init[15] = 8;
    init[16] = 0;
    init[23] = sizeof name - 1;
    memcpy(init + 24, name, sizeof name - 1);
    if (send_all(screen, init, sizeof init))
        screen->greeted = true;
}

/* One message from the viewer. */
static void hear(struct screen *screen)
{
    uint8_t type, rest[20];

    if (!receive_all(screen, &type, 1))
        return;
    switch (type) {
    case 0:                     /* pixel format: only the display's own is served */
        receive_all(screen, rest, 19);
        break;
    case 2: {                   /* encodings: only raw is served */
        if (!receive_all(screen, rest, 3))
            return;
        for (unsigned left = (unsigned)rest[1] << 8 | rest[2]; left > 0; left--)
            if (!receive_all(screen, rest, 4))
                return;
        break;
    }
    case 3:                     /* update request: byte 0 says whether changes are enough */
        if (!receive_all(screen, rest, 9))
            return;
        screen->wants = true;
        if (!rest[0])
            screen->everything = true;
        break;
    case 4:                     /* key */
        receive_all(screen, rest, 7);
        break;
    case 5:                     /* pointer */
        receive_all(screen, rest, 5);
        break;
    case 6: {                   /* text from the viewer's clipboard */
        if (!receive_all(screen, rest, 7))
            return;
        uint32_t left = (uint32_t)rest[3] << 24 | (uint32_t)rest[4] << 16 | (uint32_t)rest[5] << 8 | rest[6];
        while (left > 0) {
            uint8_t skipped[256];
            size_t part = left < sizeof skipped ? left : sizeof skipped;
            if (!receive_all(screen, skipped, part))
                return;
            left -= (uint32_t)part;
        }
        break;
    }
    default:
        drop_viewer(screen);
    }
}

/* Send the viewer the rows of the newest capture that differ from what it
 * has; nothing when none does (it stays waiting for the next capture). */
static void show(struct screen *screen)
{
    size_t row = (size_t)screen->buffer_width * 4;
    int first = 0, last = screen->buffer_height;
    uint8_t header[16] = { 0 };

    if (!screen->everything) {
        while (first < last && memcmp(screen->pixels + first * row, screen->sent + first * row, row) == 0)
            first++;
        while (last > first && memcmp(screen->pixels + (last - 1) * row, screen->sent + (last - 1) * row, row) == 0)
            last--;
        if (first == last) {
            if (++screen->unchanged >= QUIET_CAPTURES)
                screen->not_before = now_ms() + QUIET_INTERVAL_MS;
            return;
        }
    }
    screen->unchanged = 0;
    header[3] = 1;              /* one rectangle */
    put16(header + 6, (unsigned)first);
    put16(header + 8, (unsigned)screen->buffer_width);
    put16(header + 10, (unsigned)(last - first));
    memcpy(screen->sent + first * row, screen->pixels + first * row, (size_t)(last - first) * row);
    if (send_all(screen, header, sizeof header) && send_all(screen, screen->sent + first * row, (size_t)(last - first) * row))
        screen->wants = screen->everything = false;
}

int main(int argc, char **argv)
{
    struct screen screen = { .viewer = -1 };
    struct sockaddr_in address = { .sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_ANY) };
    struct wl_registry *registry;
    int listening, one = 1, port = 0;

    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--port") == 0 && index + 1 < argc)
            port = atoi(argv[++index]);
    }
    if (port <= 0 || port > 65535) {
        fprintf(stderr, "usage: emuscreen --port PORT\n");
        return 64;
    }
    signal(SIGPIPE, SIG_IGN);

    screen.display = wl_display_connect(NULL);
    if (!screen.display) {
        fprintf(stderr, "emuscreen: no compositor to connect to (is the display service running?)\n");
        return 1;
    }
    registry = wl_display_get_registry(screen.display);
    wl_registry_add_listener(registry, &registry_listener, &screen);
    wl_display_roundtrip(screen.display);
    if (!screen.shm || !screen.output || !screen.factory) {
        fprintf(stderr, "emuscreen: the compositor does not offer output capture (it has to run with --debug)\n");
        return 1;
    }
    screen.source = weston_capture_v1_create(screen.factory, screen.output, WESTON_CAPTURE_V1_SOURCE_FRAMEBUFFER);
    weston_capture_source_v1_add_listener(screen.source, &source_listener, &screen);
    wl_display_roundtrip(screen.display);      /* brings the format and the size */
    if (screen.width <= 0) {
        fprintf(stderr, "emuscreen: the compositor did not say what size its output is\n");
        return 1;
    }

    listening = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    address.sin_port = htons((uint16_t)port);
    setsockopt(listening, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    if (listening < 0 || bind(listening, (struct sockaddr *)&address, sizeof address) < 0 || listen(listening, 1) < 0) {
        perror("emuscreen: cannot listen");
        return 1;
    }
    fprintf(stderr, "emuscreen: serving the %dx%d display on port %d\n", screen.width, screen.height, port);

    while (!screen.failed) {
        struct pollfd waiting[3] = {
            { .fd = wl_display_get_fd(screen.display), .events = POLLIN },
            { .fd = listening, .events = POLLIN },
            { .fd = screen.viewer, .events = POLLIN },
        };

        int patience = -1;

        /* A viewer that waits for an update keeps captures coming. */
        if (screen.viewer >= 0 && screen.greeted && screen.wants && !screen.capturing) {
            int64_t wait = screen.not_before - now_ms();
            if (wait <= 0)
                capture(&screen);
            else
                patience = (int)wait;
        }
        if (wl_display_flush(screen.display) < 0 && errno != EAGAIN)
            break;
        if (poll(waiting, 3, patience) < 0) {
            if (errno == EINTR)
                continue;
            break;
        }
        if (waiting[0].revents & (POLLERR | POLLHUP))
            break;                              /* the compositor has gone */
        if (waiting[0].revents & POLLIN) {
            if (wl_display_dispatch(screen.display) < 0)
                break;
        }
        if (waiting[1].revents & POLLIN) {
            int connection = accept4(listening, NULL, NULL, SOCK_CLOEXEC);
            if (connection >= 0) {
                drop_viewer(&screen);           /* the newest viewer is the one served */
                struct timeval limit = { .tv_sec = 10 };

                screen.viewer = connection;
                setsockopt(connection, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
                /* A viewer that stops in the middle of a message is dropped. */
                setsockopt(connection, SOL_SOCKET, SO_RCVTIMEO, &limit, sizeof limit);
                setsockopt(connection, SOL_SOCKET, SO_SNDTIMEO, &limit, sizeof limit);
                screen.unchanged = 0;
                screen.not_before = 0;
                greet(&screen);
            }
        } else if (screen.viewer >= 0 && (waiting[2].revents & (POLLIN | POLLERR | POLLHUP))) {
            hear(&screen);
        }
        if (screen.captured) {
            screen.captured = false;
            if (screen.viewer >= 0 && screen.wants)
                show(&screen);
        }
    }
    return screen.failed ? 1 : 0;
}
