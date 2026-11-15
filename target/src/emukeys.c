/*
 * emukeys: shows which keys reach a program in the target.
 *
 *     emukeys [--until CODE] [--seconds N]
 *
 * A client of the target's compositor with one full-screen window. It prints
 * a line for every key the compositor gives it, as any program on the display
 * would get it: the Linux key code, whether it was pressed or released, and
 * the symbol the keyboard's keymap gives that code. The window shows a plain
 * picture with the marker blocks of the graphics workloads, which stays up
 * for as long as the program runs.
 *
 *     EMU-KEY: {"ready": true}                      the window has the keyboard focus
 *     EMU-KEY: {"code": 398, "state": "pressed", "symbol": "XF86Red"}
 *
 * It ends when the key with code CODE is released (--until), after N seconds
 * (--seconds, default 600), or when the compositor goes away. Exit status 2:
 * the window never got the keyboard focus.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>

#include "xdg-shell-client-protocol.h"

struct keys {
    struct wl_display *display;
    struct wl_compositor *compositor;
    struct wl_shm *shm;
    struct xdg_wm_base *shell;
    struct wl_seat *seat;
    struct wl_keyboard *keyboard;
    struct wl_surface *surface;
    struct xdg_surface *xdg_surface;
    struct xdg_toplevel *toplevel;
    struct xkb_context *xkb;
    struct xkb_keymap *keymap;
    struct xkb_state *state;
    int width, height;
    bool focused, done;
    unsigned until;
};

/* ------------------------------------------------------------- window --- */

static void draw(struct keys *keys)
{
    size_t size = (size_t)keys->width * keys->height * 4;
    struct wl_shm_pool *pool;
    struct wl_buffer *buffer;
    uint32_t *pixels;
    int fd = memfd_create("emukeys", MFD_CLOEXEC);

    if (fd < 0 || ftruncate(fd, (off_t)size) < 0)
        return;
    pixels = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (pixels == MAP_FAILED) {
        close(fd);
        return;
    }
    for (size_t index = 0; index < size / 4; index++)
        pixels[index] = 0xff203040;
    /* The marker blocks every picture of the target's display carries, so
     * that a capture can be told from any other picture and from a cut or
     * stretched one: the four corners (red, green, blue, white) and one at
     * the top centre, magenta for this program. */
    {
        static const uint32_t corner[4] = { 0xffff0000, 0xff00ff00, 0xff0000ff, 0xffffffff };
        int block = keys->height / 12;
        for (int y = 0; y < block; y++) {
            for (int x = 0; x < block; x++) {
                pixels[y * keys->width + x] = corner[0];
                pixels[y * keys->width + keys->width - block + x] = corner[1];
                pixels[(keys->height - block + y) * keys->width + x] = corner[2];
                pixels[(keys->height - block + y) * keys->width + keys->width - block + x] = corner[3];
                pixels[y * keys->width + keys->width / 2 - block / 2 + x] = 0xffff00ff;
            }
        }
    }
    munmap(pixels, size);
    pool = wl_shm_create_pool(keys->shm, fd, (int32_t)size);
    buffer = wl_shm_pool_create_buffer(pool, 0, keys->width, keys->height, keys->width * 4, WL_SHM_FORMAT_XRGB8888);
    wl_shm_pool_destroy(pool);
    close(fd);
    wl_surface_attach(keys->surface, buffer, 0, 0);
    wl_surface_damage_buffer(keys->surface, 0, 0, keys->width, keys->height);
    wl_surface_commit(keys->surface);
}

static void surface_configure(void *data, struct xdg_surface *surface, uint32_t serial)
{
    struct keys *keys = data;

    xdg_surface_ack_configure(surface, serial);
    draw(keys);
}

static const struct xdg_surface_listener surface_listener = { surface_configure };

static void toplevel_configure(void *data, struct xdg_toplevel *toplevel, int32_t width, int32_t height,
                               struct wl_array *states)
{
    struct keys *keys = data;

    (void)toplevel;
    (void)states;
    if (width > 0 && height > 0) {
        keys->width = width;
        keys->height = height;
    }
}

static void toplevel_close(void *data, struct xdg_toplevel *toplevel)
{
    struct keys *keys = data;

    (void)toplevel;
    keys->done = true;
}

static void toplevel_bounds(void *data, struct xdg_toplevel *toplevel, int32_t width, int32_t height)
{
    (void)data;
    (void)toplevel;
    (void)width;
    (void)height;
}

static void toplevel_capabilities(void *data, struct xdg_toplevel *toplevel, struct wl_array *capabilities)
{
    (void)data;
    (void)toplevel;
    (void)capabilities;
}

static const struct xdg_toplevel_listener toplevel_listener = {
    toplevel_configure, toplevel_close, toplevel_bounds, toplevel_capabilities,
};

static void shell_ping(void *data, struct xdg_wm_base *shell, uint32_t serial)
{
    (void)data;
    xdg_wm_base_pong(shell, serial);
}

static const struct xdg_wm_base_listener shell_listener = { shell_ping };

/* ----------------------------------------------------------- keyboard --- */

static void keyboard_keymap(void *data, struct wl_keyboard *keyboard, uint32_t format, int32_t fd, uint32_t size)
{
    struct keys *keys = data;
    char *text;

    (void)keyboard;
    if (format != WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1) {
        close(fd);
        return;
    }
    text = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (text != MAP_FAILED) {
        if (keys->state)
            xkb_state_unref(keys->state);
        if (keys->keymap)
            xkb_keymap_unref(keys->keymap);
        keys->keymap = xkb_keymap_new_from_string(keys->xkb, text, XKB_KEYMAP_FORMAT_TEXT_V1,
                                                  XKB_KEYMAP_COMPILE_NO_FLAGS);
        keys->state = keys->keymap ? xkb_state_new(keys->keymap) : NULL;
        munmap(text, size);
    }
    close(fd);
}

static void keyboard_enter(void *data, struct wl_keyboard *keyboard, uint32_t serial, struct wl_surface *surface,
                           struct wl_array *pressed)
{
    struct keys *keys = data;

    (void)keyboard;
    (void)serial;
    (void)surface;
    (void)pressed;
    if (!keys->focused) {
        keys->focused = true;
        printf("EMU-KEY: {\"ready\": true}\n");
        fflush(stdout);
    }
}

static void keyboard_leave(void *data, struct wl_keyboard *keyboard, uint32_t serial, struct wl_surface *surface)
{
    (void)data;
    (void)keyboard;
    (void)serial;
    (void)surface;
}

static void keyboard_key(void *data, struct wl_keyboard *keyboard, uint32_t serial, uint32_t time, uint32_t code,
                         uint32_t state)
{
    struct keys *keys = data;
    char symbol[64] = "";

    (void)keyboard;
    (void)serial;
    (void)time;
    /* The keymap counts key codes from 8. */
    if (keys->state)
        xkb_keysym_get_name(xkb_state_key_get_one_sym(keys->state, code + 8), symbol, sizeof symbol);
    printf("EMU-KEY: {\"code\": %u, \"state\": \"%s\", \"symbol\": \"%s\"}\n", code,
           state == WL_KEYBOARD_KEY_STATE_PRESSED ? "pressed" : "released", symbol);
    fflush(stdout);
    if (code == keys->until && state == WL_KEYBOARD_KEY_STATE_RELEASED)
        keys->done = true;
}

static void keyboard_modifiers(void *data, struct wl_keyboard *keyboard, uint32_t serial, uint32_t depressed,
                               uint32_t latched, uint32_t locked, uint32_t group)
{
    struct keys *keys = data;

    (void)keyboard;
    (void)serial;
    if (keys->state)
        xkb_state_update_mask(keys->state, depressed, latched, locked, 0, 0, group);
}

static void keyboard_repeat(void *data, struct wl_keyboard *keyboard, int32_t rate, int32_t delay)
{
    (void)data;
    (void)keyboard;
    (void)rate;
    (void)delay;
}

static const struct wl_keyboard_listener keyboard_listener = {
    keyboard_keymap, keyboard_enter, keyboard_leave, keyboard_key, keyboard_modifiers, keyboard_repeat,
};

static void seat_capabilities(void *data, struct wl_seat *seat, uint32_t capabilities)
{
    struct keys *keys = data;

    if ((capabilities & WL_SEAT_CAPABILITY_KEYBOARD) && !keys->keyboard) {
        keys->keyboard = wl_seat_get_keyboard(seat);
        wl_keyboard_add_listener(keys->keyboard, &keyboard_listener, keys);
    }
}

static void seat_name(void *data, struct wl_seat *seat, const char *name)
{
    (void)data;
    (void)seat;
    (void)name;
}

static const struct wl_seat_listener seat_listener = { seat_capabilities, seat_name };

static void on_global(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
    struct keys *keys = data;

    if (strcmp(interface, wl_compositor_interface.name) == 0) {
        keys->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, version < 4 ? version : 4);
    } else if (strcmp(interface, wl_shm_interface.name) == 0) {
        keys->shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
    } else if (strcmp(interface, xdg_wm_base_interface.name) == 0) {
        keys->shell = wl_registry_bind(registry, name, &xdg_wm_base_interface, version < 4 ? version : 4);
        xdg_wm_base_add_listener(keys->shell, &shell_listener, keys);
    } else if (strcmp(interface, wl_seat_interface.name) == 0) {
        /* Every seat: a key is a key whichever seat's keyboard it is on. */
        struct wl_seat *seat = wl_registry_bind(registry, name, &wl_seat_interface, version < 4 ? version : 4);
        wl_seat_add_listener(seat, &seat_listener, keys);
        keys->seat = seat;
    }
}

static void on_global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
    (void)data;
    (void)registry;
    (void)name;
}

static const struct wl_registry_listener registry_listener = { on_global, on_global_remove };

int main(int argc, char **argv)
{
    struct keys keys = { .width = 1280, .height = 720 };
    struct wl_registry *registry;
    struct timespec started, now;
    int seconds = 600;

    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--until") == 0 && index + 1 < argc)
            keys.until = (unsigned)atoi(argv[++index]);
        else if (strcmp(argv[index], "--seconds") == 0 && index + 1 < argc)
            seconds = atoi(argv[++index]);
        else {
            fprintf(stderr, "usage: emukeys [--until CODE] [--seconds N]\n");
            return 64;
        }
    }
    keys.xkb = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    keys.display = wl_display_connect(NULL);
    if (!keys.display) {
        fprintf(stderr, "emukeys: no compositor to connect to (is the display service running?)\n");
        return 1;
    }
    registry = wl_display_get_registry(keys.display);
    wl_registry_add_listener(registry, &registry_listener, &keys);
    wl_display_roundtrip(keys.display);
    if (!keys.compositor || !keys.shm || !keys.shell) {
        fprintf(stderr, "emukeys: the compositor lacks an interface this program needs\n");
        return 1;
    }
    if (!keys.seat) {
        fprintf(stderr, "emukeys: the compositor has no seat, so no keyboard: remote control input is not turned on "
                        "for this display\n");
        return 2;
    }
    keys.surface = wl_compositor_create_surface(keys.compositor);
    keys.xdg_surface = xdg_wm_base_get_xdg_surface(keys.shell, keys.surface);
    xdg_surface_add_listener(keys.xdg_surface, &surface_listener, &keys);
    keys.toplevel = xdg_surface_get_toplevel(keys.xdg_surface);
    xdg_toplevel_add_listener(keys.toplevel, &toplevel_listener, &keys);
    xdg_toplevel_set_title(keys.toplevel, "emukeys");
    xdg_toplevel_set_fullscreen(keys.toplevel, NULL);
    wl_surface_commit(keys.surface);

    clock_gettime(CLOCK_MONOTONIC, &started);
    while (!keys.done) {
        struct pollfd waiting = { .fd = wl_display_get_fd(keys.display), .events = POLLIN };

        if (wl_display_flush(keys.display) < 0 && errno != EAGAIN)
            break;
        clock_gettime(CLOCK_MONOTONIC, &now);
        if (now.tv_sec - started.tv_sec >= seconds)
            break;
        if (poll(&waiting, 1, 500) < 0 && errno != EINTR)
            break;
        if (waiting.revents & (POLLERR | POLLHUP))
            break;
        if (waiting.revents & POLLIN) {
            if (wl_display_dispatch(keys.display) < 0)
                break;
        } else {
            wl_display_dispatch_pending(keys.display);
        }
    }
    return keys.focused ? 0 : 2;
}
