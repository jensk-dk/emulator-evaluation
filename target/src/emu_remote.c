/*
 * emu-remote: remote control key input for the target's compositor.
 *
 * A module for Weston (loaded by /opt/emu/display with --modules). It gives
 * the compositor a seat of its own with a keyboard, the "remote control", and
 * presses and releases keys on it as it is told on a socket:
 *
 *     /run/emu/remote.sock      lines of text, one command each:
 *         press CODE            CODE is a Linux key code (KEY_UP is 103)
 *         release CODE
 *
 * The client that has the keyboard focus gets the key like any other key of
 * a keyboard: its code, and the symbol the keymap gives it. The keymap is the
 * target's own (pc, us, the multimedia keys of evdev) with symbols added for
 * the remote control keys that have a code but no symbol there.
 *
 * Why a module: the keys of a remote control (the colour keys, say) have
 * Linux key codes that no PC keyboard sends, so neither an emulated keyboard
 * device nor a VNC connection can carry them; and in container mode the
 * compositor has no input device at all.
 *
 * It uses three functions of libweston that the library exports for its own
 * backends and declares in headers the development package does not install
 * (libweston/backend.h and libweston-internal.h, Weston 14). They are
 * declared here as they are there.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#include <libweston/libweston.h>
#include <xkbcommon/xkbcommon.h>

void weston_seat_init(struct weston_seat *seat, struct weston_compositor *ec, const char *seat_name);
int weston_seat_init_keyboard(struct weston_seat *seat, struct xkb_keymap *keymap);
void notify_key(struct weston_seat *seat, const struct timespec *time, uint32_t key,
                enum wl_keyboard_key_state state, enum weston_key_state_update update_state);

#define SOCKET_PATH "/run/emu/remote.sock"

/* Keys whose codes the target's keymap leaves without a symbol. The names in
 * angle brackets are the keymap's: the Linux key code plus 8. */
static const char KEYMAP[] =
    "xkb_keymap {\n"
    "  xkb_keycodes { include \"evdev+aliases(qwerty)\" };\n"
    "  xkb_types { include \"complete\" };\n"
    "  xkb_compat { include \"complete\" };\n"
    "  xkb_symbols {\n"
    "    include \"pc+us+inet(evdev)\"\n"
    "    key <I406> { [ XF86Red ] };\n"         /* KEY_RED 398 */
    "    key <I407> { [ XF86Green ] };\n"       /* KEY_GREEN 399 */
    "    key <I408> { [ XF86Yellow ] };\n"      /* KEY_YELLOW 400 */
    "    key <I409> { [ XF86Blue ] };\n"        /* KEY_BLUE 401 */
    "  };\n"
    "};\n";

struct remote {
    struct weston_compositor *compositor;
    struct weston_seat seat;
    struct wl_event_source *listening;
    int fd;
    struct wl_listener activated;
    struct wl_listener destroyed;
};

struct client {
    struct remote *remote;
    struct wl_event_source *source;
    int fd;
    char line[128];
    size_t used;
};

static void run_line(struct remote *remote, char *line)
{
    char word[16];
    unsigned int code;
    struct timespec now;

    if (sscanf(line, "%15s %u", word, &code) != 2 || code == 0 || code > 767)
        return;
    weston_compositor_get_time(&now);
    if (strcmp(word, "press") == 0)
        notify_key(&remote->seat, &now, code, WL_KEYBOARD_KEY_STATE_PRESSED, STATE_UPDATE_AUTOMATIC);
    else if (strcmp(word, "release") == 0)
        notify_key(&remote->seat, &now, code, WL_KEYBOARD_KEY_STATE_RELEASED, STATE_UPDATE_AUTOMATIC);
}

static int client_readable(int fd, uint32_t mask, void *data)
{
    struct client *client = data;
    ssize_t count = -1;

    if (mask & WL_EVENT_READABLE)
        count = read(fd, client->line + client->used, sizeof client->line - 1 - client->used);
    if (count <= 0) {
        if (count < 0 && (errno == EINTR || errno == EAGAIN) && !(mask & (WL_EVENT_HANGUP | WL_EVENT_ERROR)))
            return 0;
        wl_event_source_remove(client->source);
        close(fd);
        free(client);
        return 0;
    }
    client->used += (size_t)count;
    client->line[client->used] = '\0';
    for (;;) {
        char *end = strchr(client->line, '\n');
        if (!end)
            break;
        *end = '\0';
        run_line(client->remote, client->line);
        client->used -= (size_t)(end + 1 - client->line);
        memmove(client->line, end + 1, client->used + 1);
    }
    if (client->used >= sizeof client->line - 1)
        client->used = 0;       /* not a command: drop it */
    return 0;
}

static int connection_waiting(int fd, uint32_t mask, void *data)
{
    struct remote *remote = data;
    struct client *client;
    int connection;

    (void)mask;
    connection = accept4(fd, NULL, NULL, SOCK_CLOEXEC | SOCK_NONBLOCK);
    if (connection < 0)
        return 0;
    client = calloc(1, sizeof *client);
    if (!client) {
        close(connection);
        return 0;
    }
    client->remote = remote;
    client->fd = connection;
    client->source = wl_event_loop_add_fd(wl_display_get_event_loop(remote->compositor->wl_display), connection,
                                          WL_EVENT_READABLE, client_readable, client);
    return 0;
}

/* The shell gives the keyboard focus to the first seat the compositor has.
 * Where that is another seat, this one follows it. */
static void surface_activated(struct wl_listener *listener, void *data)
{
    struct remote *remote = wl_container_of(listener, remote, activated);
    struct weston_surface_activation_data *activation = data;

    if (activation->seat != &remote->seat && activation->view)
        weston_seat_set_keyboard_focus(&remote->seat, activation->view->surface);
}

static void compositor_destroyed(struct wl_listener *listener, void *data)
{
    struct remote *remote = wl_container_of(listener, remote, destroyed);

    (void)data;
    if (remote->listening)
        wl_event_source_remove(remote->listening);
    if (remote->fd >= 0)
        close(remote->fd);
    unlink(SOCKET_PATH);
}

WL_EXPORT int wet_module_init(struct weston_compositor *compositor, int *argc, char *argv[])
{
    struct remote *remote;
    struct sockaddr_un address = { .sun_family = AF_UNIX };
    struct xkb_context *context;
    struct xkb_keymap *keymap = NULL;

    (void)argc;
    (void)argv;
    remote = calloc(1, sizeof *remote);
    if (!remote)
        return -1;
    remote->compositor = compositor;
    remote->fd = -1;

    context = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    if (context)
        keymap = xkb_keymap_new_from_string(context, KEYMAP, XKB_KEYMAP_FORMAT_TEXT_V1, XKB_KEYMAP_COMPILE_NO_FLAGS);
    if (!keymap)
        weston_log("emu-remote: the remote control's keymap could not be made; using the compositor's own\n");
    weston_seat_init(&remote->seat, compositor, "emu-remote");
    if (weston_seat_init_keyboard(&remote->seat, keymap) < 0) {
        weston_log("emu-remote: the remote control's keyboard could not be made\n");
        return -1;
    }
    if (keymap)
        xkb_keymap_unref(keymap);
    if (context)
        xkb_context_unref(context);

    remote->fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    strncpy(address.sun_path, SOCKET_PATH, sizeof address.sun_path - 1);
    unlink(SOCKET_PATH);
    if (remote->fd < 0 || bind(remote->fd, (struct sockaddr *)&address, sizeof address) < 0 ||
        listen(remote->fd, 4) < 0) {
        weston_log("emu-remote: cannot listen on %s: %s\n", SOCKET_PATH, strerror(errno));
        return -1;
    }
    chmod(SOCKET_PATH, 0600);
    remote->listening = wl_event_loop_add_fd(wl_display_get_event_loop(compositor->wl_display), remote->fd,
                                             WL_EVENT_READABLE, connection_waiting, remote);

    remote->activated.notify = surface_activated;
    wl_signal_add(&compositor->activate_signal, &remote->activated);
    remote->destroyed.notify = compositor_destroyed;
    wl_signal_add(&compositor->destroy_signal, &remote->destroyed);
    weston_log("emu-remote: remote control keys are taken on %s\n", SOCKET_PATH);
    return 0;
}
