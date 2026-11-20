/*
 * The emulator's remote control as an input device of the target.
 *
 * The launcher's display window sends each key of the remote control (typed
 * on the host's keyboard, clicked on the on-screen remote control, or received
 * from a RedRat) as a line, "press CODE" or "release CODE", CODE a Linux key
 * code (emulator/remote.py). On an RDK-E target the lines arrive on a port of
 * the VM's virtio serial device named "tvemu.remote". This program makes a
 * keyboard of the uinput driver, "tvemu remote control", and passes the keys
 * on as its key events. A compositor that reads the kernel's input devices,
 * as Westeros does, takes them like the keys of any remote control.
 */
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/uinput.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define PORT_NAME "tvemu.remote"

/* The device node of the virtio serial port with our name, or -1. */
static int open_port(void)
{
    DIR *ports = opendir("/sys/class/virtio-ports");
    struct dirent *entry;
    int fd = -1;

    if (!ports)
        return -1;
    while (fd < 0 && (entry = readdir(ports))) {
        char path[300], name[64] = "";
        FILE *file;

        if (entry->d_name[0] == '.')
            continue;
        snprintf(path, sizeof path, "/sys/class/virtio-ports/%s/name", entry->d_name);
        file = fopen(path, "r");
        if (!file)
            continue;
        if (fgets(name, sizeof name, file))
            name[strcspn(name, "\n")] = 0;
        fclose(file);
        if (strcmp(name, PORT_NAME))
            continue;
        snprintf(path, sizeof path, "/dev/%s", entry->d_name);
        fd = open(path, O_RDONLY);
    }
    closedir(ports);
    return fd;
}

static int make_keyboard(void)
{
    struct uinput_user_dev device;
    int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    int code;

    if (fd < 0)
        return -1;
    ioctl(fd, UI_SET_EVBIT, EV_KEY);
    ioctl(fd, UI_SET_EVBIT, EV_SYN);
    /* Every key code: which keys a remote control has is the launcher's to say. */
    for (code = 1; code < KEY_MAX; code++)
        if (code < BTN_MISC || code >= KEY_OK)
            ioctl(fd, UI_SET_KEYBIT, code);
    memset(&device, 0, sizeof device);
    snprintf(device.name, UINPUT_MAX_NAME_SIZE, "tvemu remote control");
    device.id.bustype = BUS_VIRTUAL;
    device.id.vendor = 0x7476;
    device.id.product = 0x0001;
    device.id.version = 1;
    if (write(fd, &device, sizeof device) != sizeof device || ioctl(fd, UI_DEV_CREATE) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static void emit(int fd, int type, int code, int value)
{
    struct input_event event;

    memset(&event, 0, sizeof event);
    event.type = type;
    event.code = code;
    event.value = value;
    if (write(fd, &event, sizeof event) != sizeof event)
        perror("tvemu-remote: key event");
}

static void command(int keyboard, const char *line)
{
    int code, value;

    if (sscanf(line, "press %d", &code) == 1)
        value = 1;
    else if (sscanf(line, "release %d", &code) == 1)
        value = 0;
    else
        return;
    if (code <= 0 || code >= KEY_MAX)
        return;
    emit(keyboard, EV_KEY, code, value);
    emit(keyboard, EV_SYN, SYN_REPORT, 0);
    printf("tvemu-remote: %s %d\n", value ? "press" : "release", code);
    fflush(stdout);
}

int main(void)
{
    int keyboard = make_keyboard();
    char pending[256];
    size_t held = 0;

    if (keyboard < 0) {
        fprintf(stderr, "tvemu-remote: no uinput keyboard: %s\n", strerror(errno));
        return 1;
    }
    printf("tvemu-remote: keyboard \"tvemu remote control\" made\n");
    fflush(stdout);
    for (;;) {
        int port = open_port();
        ssize_t got;

        if (port < 0) {
            /* The emulator gave the VM no such port: no window, no keys. */
            sleep(2);
            continue;
        }
        /* Nothing arrives, and reading returns at once, while the launcher's
           window is not connected to the port. */
        while ((got = read(port, pending + held, sizeof pending - held - 1)) > 0) {
            char *start = pending, *end;

            held += (size_t)got;
            pending[held] = 0;
            while ((end = strchr(start, '\n'))) {
                *end = 0;
                command(keyboard, start);
                start = end + 1;
            }
            held = strlen(start);
            memmove(pending, start, held);
            if (held >= sizeof pending - 1)
                held = 0;       /* a line longer than any command: dropped */
        }
        close(port);
        held = 0;
        usleep(200000);
    }
}
