/*
 * emu-coreaudio: the launcher's audio player for macOS hosts.
 *
 * macOS ships no program that plays raw samples from its standard input, the
 * way pacat, pw-cat and aplay do on Linux, so the launcher builds this one
 * (emulator/host.py) and the host-side audio process (emulator/hostaudio.py)
 * uses it as its player program.
 *
 *   emu-coreaudio play [--device NAME_OR_UID] [--volume 0..100] [--monitor FILE]
 *       Plays 16-bit little-endian stereo at 48 kHz from standard input on an
 *       output device (the system default unless one is named), through an
 *       audio queue. With --monitor, everything the queue takes for the
 *       device is also written to FILE, and a summary to FILE.json on exit.
 *   emu-coreaudio devices
 *       The output devices, as JSON.
 *   emu-coreaudio activity PID
 *       What the audio server says about a process: whether it is playing, and
 *       on which devices. JSON; needs macOS 14.2.
 *
 * The sound arrives at the target's pace and leaves at the output device's.
 * A short buffer in between takes up the difference: when it runs empty the
 * device gets silence, and when it overflows the oldest sound is dropped, so
 * the delay stays short.
 */
#include <AudioToolbox/AudioToolbox.h>
#include <CoreAudio/CoreAudio.h>
#include <CoreFoundation/CoreFoundation.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define RATE 48000
#define CHANNELS 2
#define FRAME_BYTES 4
#define BUFFER_BYTES (RATE / 50 * FRAME_BYTES)      /* what the queue takes at a time: 20 ms */
#define QUEUE_BUFFERS 3
#define RING_BYTES (RATE / 2 * FRAME_BYTES)         /* at most half a second waits to be played */
#define START_BYTES (2 * BUFFER_BYTES)              /* sound to have before the device starts */

static const AudioObjectPropertyAddress DEVICES = {kAudioHardwarePropertyDevices, kAudioObjectPropertyScopeGlobal,
                                                   kAudioObjectPropertyElementMain};

static void print_json_string(FILE *out, const char *text)
{
    fputc('"', out);
    for (const unsigned char *c = (const unsigned char *)(text ? text : ""); *c; c++) {
        if (*c == '"' || *c == '\\')
            fprintf(out, "\\%c", *c);
        else if (*c < 0x20)
            fprintf(out, "\\u%04x", *c);
        else
            fputc(*c, out);
    }
    fputc('"', out);
}

/* A string property of an audio object, as UTF-8; empty when it has none. */
static void string_property(AudioObjectID object, AudioObjectPropertySelector selector, char *out, size_t size)
{
    AudioObjectPropertyAddress address = {selector, kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain};
    CFStringRef value = NULL;
    UInt32 bytes = sizeof value;
    out[0] = 0;
    if (AudioObjectGetPropertyData(object, &address, 0, NULL, &bytes, &value) != noErr || !value)
        return;
    if (!CFStringGetCString(value, out, (CFIndex)size, kCFStringEncodingUTF8))
        out[0] = 0;
    CFRelease(value);
}

static int output_channels(AudioDeviceID device)
{
    AudioObjectPropertyAddress address = {kAudioDevicePropertyStreamConfiguration, kAudioObjectPropertyScopeOutput,
                                          kAudioObjectPropertyElementMain};
    UInt32 bytes = 0;
    if (AudioObjectGetPropertyDataSize(device, &address, 0, NULL, &bytes) != noErr || !bytes)
        return 0;
    AudioBufferList *list = malloc(bytes);
    int channels = 0;
    if (AudioObjectGetPropertyData(device, &address, 0, NULL, &bytes, list) == noErr)
        for (UInt32 i = 0; i < list->mNumberBuffers; i++)
            channels += (int)list->mBuffers[i].mNumberChannels;
    free(list);
    return channels;
}

static AudioDeviceID default_output(void)
{
    AudioObjectPropertyAddress address = {kAudioHardwarePropertyDefaultOutputDevice, kAudioObjectPropertyScopeGlobal,
                                          kAudioObjectPropertyElementMain};
    AudioDeviceID device = kAudioObjectUnknown;
    UInt32 bytes = sizeof device;
    AudioObjectGetPropertyData(kAudioObjectSystemObject, &address, 0, NULL, &bytes, &device);
    return device;
}

/* Every audio device; the caller frees the list. */
static AudioDeviceID *all_devices(int *count)
{
    UInt32 bytes = 0;
    *count = 0;
    if (AudioObjectGetPropertyDataSize(kAudioObjectSystemObject, &DEVICES, 0, NULL, &bytes) != noErr || !bytes)
        return NULL;
    AudioDeviceID *devices = malloc(bytes);
    if (AudioObjectGetPropertyData(kAudioObjectSystemObject, &DEVICES, 0, NULL, &bytes, devices) != noErr) {
        free(devices);
        return NULL;
    }
    *count = (int)(bytes / sizeof(AudioDeviceID));
    return devices;
}

static int list_devices(void)
{
    int count;
    AudioDeviceID *devices = all_devices(&count);
    AudioDeviceID chosen = default_output();
    int printed = 0;
    printf("[");
    for (int i = 0; i < count; i++) {
        char name[256], uid[256];
        int channels = output_channels(devices[i]);
        if (!channels)
            continue;
        string_property(devices[i], kAudioObjectPropertyName, name, sizeof name);
        string_property(devices[i], kAudioDevicePropertyDeviceUID, uid, sizeof uid);
        printf("%s{\"name\": ", printed++ ? ", " : "");
        print_json_string(stdout, name);
        printf(", \"uid\": ");
        print_json_string(stdout, uid);
        printf(", \"channels\": %d, \"default\": %s}", channels, devices[i] == chosen ? "true" : "false");
    }
    printf("]\n");
    free(devices);
    return 0;
}

/* The output device with this name or unique identifier, or 0. */
static AudioDeviceID find_device(const char *wanted)
{
    int count;
    AudioDeviceID *devices = all_devices(&count), found = kAudioObjectUnknown;
    for (int i = 0; i < count && found == kAudioObjectUnknown; i++) {
        char name[256], uid[256];
        if (!output_channels(devices[i]))
            continue;
        string_property(devices[i], kAudioObjectPropertyName, name, sizeof name);
        string_property(devices[i], kAudioDevicePropertyDeviceUID, uid, sizeof uid);
        if (!strcmp(wanted, name) || !strcmp(wanted, uid))
            found = devices[i];
    }
    free(devices);
    return found;
}

static int process_activity(pid_t pid)
{
    printf("{\"pid\": %d", (int)pid);
#if defined(__MAC_14_2) || (defined(__MAC_OS_X_VERSION_MAX_ALLOWED) && __MAC_OS_X_VERSION_MAX_ALLOWED >= 140200)
    if (__builtin_available(macOS 14.2, *)) {
        AudioObjectPropertyAddress translate = {kAudioHardwarePropertyTranslatePIDToProcessObject,
                                                kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain};
        AudioObjectID process = kAudioObjectUnknown;
        UInt32 bytes = sizeof process;
        OSStatus status = AudioObjectGetPropertyData(kAudioObjectSystemObject, &translate, sizeof pid, &pid, &bytes,
                                                     &process);
        if (status != noErr || process == kAudioObjectUnknown) {
            printf(", \"known\": false}\n");
            return 0;
        }
        AudioObjectPropertyAddress running = {kAudioProcessPropertyIsRunningOutput, kAudioObjectPropertyScopeGlobal,
                                              kAudioObjectPropertyElementMain};
        UInt32 playing = 0;
        bytes = sizeof playing;
        AudioObjectGetPropertyData(process, &running, 0, NULL, &bytes, &playing);
        printf(", \"known\": true, \"playing\": %s, \"devices\": [", playing ? "true" : "false");
        AudioObjectPropertyAddress used = {kAudioProcessPropertyDevices, kAudioObjectPropertyScopeOutput,
                                           kAudioObjectPropertyElementMain};
        bytes = 0;
        if (AudioObjectGetPropertyDataSize(process, &used, 0, NULL, &bytes) == noErr && bytes) {
            AudioObjectID *devices = malloc(bytes);
            if (AudioObjectGetPropertyData(process, &used, 0, NULL, &bytes, devices) == noErr)
                for (UInt32 i = 0; i < bytes / sizeof(AudioObjectID); i++) {
                    char name[256];
                    string_property(devices[i], kAudioObjectPropertyName, name, sizeof name);
                    printf("%s", i ? ", " : "");
                    print_json_string(stdout, name);
                }
            free(devices);
        }
        printf("]}\n");
        return 0;
    }
#endif
    printf(", \"known\": null, \"reason\": \"the audio server reports processes from macOS 14.2 on\"}\n");
    return 0;
}

/* ---------------------------------------------------------------- play --- */

struct player {
    pthread_mutex_t lock;
    unsigned char ring[RING_BYTES];
    size_t head, fill;              /* where the oldest waiting byte is, and how many wait */
    FILE *monitor;
    unsigned long long taken;       /* bytes the queue took for the device, silence included */
    unsigned long long sound;       /* of those, bytes that came from standard input */
    unsigned long long dropped;     /* bytes dropped because the buffer was full */
};

static volatile sig_atomic_t interrupted;

static void on_signal(int number)
{
    (void)number;
    interrupted = 1;
}

/* The queue wants the next 20 ms for the output device. */
static void fill_buffer(void *user, AudioQueueRef queue, AudioQueueBufferRef buffer)
{
    struct player *p = user;
    size_t want = buffer->mAudioDataBytesCapacity;
    unsigned char *out = buffer->mAudioData;
    pthread_mutex_lock(&p->lock);
    size_t have = p->fill < want ? p->fill - p->fill % FRAME_BYTES : want;
    size_t first = have < RING_BYTES - p->head ? have : RING_BYTES - p->head;
    memcpy(out, p->ring + p->head, first);
    memcpy(out + first, p->ring, have - first);
    p->head = (p->head + have) % RING_BYTES;
    p->fill -= have;
    p->taken += want;
    p->sound += have;
    pthread_mutex_unlock(&p->lock);
    memset(out + have, 0, want - have);
    buffer->mAudioDataByteSize = (UInt32)want;
    if (p->monitor)
        fwrite(out, 1, want, p->monitor);
    AudioQueueEnqueueBuffer(queue, buffer, 0, NULL);
}

static void store(struct player *p, const unsigned char *data, size_t bytes)
{
    pthread_mutex_lock(&p->lock);
    if (bytes > RING_BYTES) {
        p->dropped += bytes - RING_BYTES;
        data += bytes - RING_BYTES;
        bytes = RING_BYTES;
    }
    if (p->fill + bytes > RING_BYTES) {
        size_t excess = p->fill + bytes - RING_BYTES;
        excess += (FRAME_BYTES - excess % FRAME_BYTES) % FRAME_BYTES;
        p->head = (p->head + excess) % RING_BYTES;
        p->fill -= excess;
        p->dropped += excess;
    }
    size_t tail = (p->head + p->fill) % RING_BYTES;
    size_t first = bytes < RING_BYTES - tail ? bytes : RING_BYTES - tail;
    memcpy(p->ring + tail, data, first);
    memcpy(p->ring, data + first, bytes - first);
    p->fill += bytes;
    pthread_mutex_unlock(&p->lock);
}

static int play(const char *device_name, double volume, const char *monitor_path)
{
    static struct player p;
    pthread_mutex_init(&p.lock, NULL);
    if (monitor_path && !(p.monitor = fopen(monitor_path, "wb"))) {
        fprintf(stderr, "emu-coreaudio: cannot write %s\n", monitor_path);
        return 1;
    }

    AudioStreamBasicDescription format = {
        .mSampleRate = RATE,
        .mFormatID = kAudioFormatLinearPCM,
        .mFormatFlags = kLinearPCMFormatFlagIsSignedInteger | kLinearPCMFormatFlagIsPacked,
        .mBytesPerPacket = FRAME_BYTES,
        .mFramesPerPacket = 1,
        .mBytesPerFrame = FRAME_BYTES,
        .mChannelsPerFrame = CHANNELS,
        .mBitsPerChannel = 16,
    };
    AudioQueueRef queue;
    if (AudioQueueNewOutput(&format, fill_buffer, &p, NULL, NULL, 0, &queue) != noErr) {
        fprintf(stderr, "emu-coreaudio: the audio queue could not be created\n");
        return 1;
    }
    AudioDeviceID device = default_output();
    if (device_name && *device_name) {
        device = find_device(device_name);
        if (device == kAudioObjectUnknown) {
            fprintf(stderr, "emu-coreaudio: no output device is named %s (see: emu-coreaudio devices)\n", device_name);
            return 1;
        }
        AudioObjectPropertyAddress address = {kAudioDevicePropertyDeviceUID, kAudioObjectPropertyScopeGlobal,
                                              kAudioObjectPropertyElementMain};
        CFStringRef uid = NULL;
        UInt32 bytes = sizeof uid;
        if (AudioObjectGetPropertyData(device, &address, 0, NULL, &bytes, &uid) != noErr ||
            AudioQueueSetProperty(queue, kAudioQueueProperty_CurrentDevice, &uid, sizeof uid) != noErr) {
            fprintf(stderr, "emu-coreaudio: the output device %s could not be selected\n", device_name);
            return 1;
        }
    }
    AudioQueueSetParameter(queue, kAudioQueueParam_Volume, (AudioQueueParameterValue)(volume / 100.0));

    signal(SIGTERM, on_signal);
    signal(SIGINT, on_signal);
    signal(SIGPIPE, SIG_IGN);

    unsigned char block[BUFFER_BYTES];
    int started = 0;
    OSStatus start_status = noErr;
    while (!interrupted) {
        ssize_t got = read(STDIN_FILENO, block, sizeof block);
        if (got <= 0)
            break;
        store(&p, block, (size_t)got);
        if (!started && p.fill >= START_BYTES) {
            for (int i = 0; i < QUEUE_BUFFERS; i++) {
                AudioQueueBufferRef buffer;
                if (AudioQueueAllocateBuffer(queue, BUFFER_BYTES, &buffer) == noErr)
                    fill_buffer(&p, queue, buffer);
            }
            start_status = AudioQueueStart(queue, NULL);
            if (start_status != noErr) {
                fprintf(stderr, "emu-coreaudio: the output device did not start (status %d)\n", (int)start_status);
                break;
            }
            started = 1;
        }
    }
    /* Let what still waits reach the device, then stop. */
    for (int i = 0; started && !interrupted && i < 100; i++) {
        pthread_mutex_lock(&p.lock);
        size_t waiting = p.fill;
        pthread_mutex_unlock(&p.lock);
        if (waiting < FRAME_BYTES)
            break;
        usleep(10000);
    }
    double device_seconds = 0;
    if (started) {
        usleep(QUEUE_BUFFERS * 20000);
        AudioTimeStamp stamp = {0};
        if (AudioQueueGetCurrentTime(queue, NULL, &stamp, NULL) == noErr && (stamp.mFlags & kAudioTimeStampSampleTimeValid))
            device_seconds = stamp.mSampleTime / RATE;
        AudioQueueStop(queue, true);
    }
    AudioQueueDispose(queue, true);

    if (p.monitor) {
        fclose(p.monitor);
        char path[1100], name[256], uid[256];
        snprintf(path, sizeof path, "%s.json", monitor_path);
        FILE *summary = fopen(path, "w");
        if (summary) {
            string_property(device, kAudioObjectPropertyName, name, sizeof name);
            string_property(device, kAudioDevicePropertyDeviceUID, uid, sizeof uid);
            fprintf(summary, "{\"device\": ");
            print_json_string(summary, name);
            fprintf(summary, ", \"uid\": ");
            print_json_string(summary, uid);
            fprintf(summary, ", \"volume\": %.0f, \"started\": %s, \"taken_seconds\": %.3f, \"sound_seconds\": %.3f, "
                             "\"dropped_seconds\": %.3f, \"device_clock_seconds\": %.3f}\n",
                    volume, started ? "true" : "false", (double)p.taken / (RATE * FRAME_BYTES),
                    (double)p.sound / (RATE * FRAME_BYTES), (double)p.dropped / (RATE * FRAME_BYTES), device_seconds);
            fclose(summary);
        }
    }
    return start_status == noErr ? 0 : 1;
}

int main(int argc, char **argv)
{
    if (argc >= 2 && !strcmp(argv[1], "devices"))
        return list_devices();
    if (argc >= 3 && !strcmp(argv[1], "activity"))
        return process_activity((pid_t)atoi(argv[2]));
    if (argc >= 2 && !strcmp(argv[1], "play")) {
        const char *device = NULL, *monitor = NULL;
        double volume = 100;
        for (int i = 2; i < argc; i++) {
            if (!strcmp(argv[i], "--device") && i + 1 < argc)
                device = argv[++i];
            else if (!strcmp(argv[i], "--volume") && i + 1 < argc)
                volume = atof(argv[++i]);
            else if (!strcmp(argv[i], "--monitor") && i + 1 < argc)
                monitor = argv[++i];
            else {
                fprintf(stderr, "emu-coreaudio: unknown argument %s\n", argv[i]);
                return 64;
            }
        }
        if (volume < 0 || volume > 100) {
            fprintf(stderr, "emu-coreaudio: --volume is from 0 to 100\n");
            return 64;
        }
        return play(device, volume, monitor);
    }
    fprintf(stderr, "usage: emu-coreaudio play [--device NAME_OR_UID] [--volume 0..100] [--monitor FILE]\n"
                    "       emu-coreaudio devices\n"
                    "       emu-coreaudio activity PID\n");
    return 64;
}
