/*
 * emugfx - graphics workloads for the emulator evaluation.
 *
 * Each test presents the same kind of fixed animated scene through one
 * graphics technology, in a fullscreen window on the target's Wayland
 * display, and reports how fast it ran:
 *
 *   emugfx wayland   the CPU draws into shared-memory buffers (wl_shm)
 *   emugfx gles      OpenGL ES 2.0 through EGL
 *   emugfx vulkan    Vulkan through the Wayland window-system integration
 *   emugfx info      the OpenGL ES renderer and Vulkan device of the display
 *
 * The animation advances by frame number, not by time, so every run draws
 * the same sequence of frames however fast it goes. Frames are submitted as
 * fast as they can be rendered, without waiting for the display's refresh;
 * the compositor reports separately how many of them reached the display.
 *
 * Every frame carries fixed marker blocks (corners, and one at the top centre
 * whose colour names the technology), so a capture of the display can be
 * checked from the host.
 *
 * Output: one "EMU-RESULT:" line. With --hold, the last frame stays on the
 * display and an "EMU-SCREEN:" line tells the launcher to capture it.
 *
 * The version is the workload's: see target/rootfs/opt/emu/workloads/graphics-demo.
 */
#define _GNU_SOURCE

#include <errno.h>
#include <math.h>
#include <poll.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include <wayland-client.h>
#include <wayland-egl.h>
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#define VK_USE_PLATFORM_WAYLAND_KHR
#include <vulkan/vulkan.h>

#include "presentation-time-client-protocol.h"
#include "xdg-shell-client-protocol.h"
#include "shaders.h" /* SPIR-V, generated from target/src/shaders at build time */

#define NQUADS 64
#define QUAD_VERTICES (NQUADS * 6)
#define PI 3.14159265358979323846

struct rgb {
    uint8_t r, g, b;
};

/* Marker blocks, each height/12 square: the four corners in this order (top
 * left, top right, bottom left, bottom right), and a block twice as wide at
 * the top centre in the technology's colour. The launcher checks the same
 * colours (emulator/graphics.py) and so does the Flutter demo. */
static const struct rgb CORNER[4] = {{255, 0, 0}, {0, 255, 0}, {0, 0, 255}, {255, 255, 255}};
static const struct rgb MARK_WAYLAND = {255, 128, 0};
static const struct rgb MARK_GLES = {0, 200, 255};
static const struct rgb MARK_VULKAN = {200, 0, 255};

static const char *test_name = "info";
static double opt_seconds = 5.0;
static double opt_hold = 0.0;
static double process_start;

static double now(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static void json_string(const char *text)
{
    putchar('"');
    for (const unsigned char *c = (const unsigned char *)(text ? text : ""); *c; c++) {
        if (*c == '"' || *c == '\\')
            printf("\\%c", *c);
        else if (*c < 0x20)
            printf("\\u%04x", *c);
        else
            putchar(*c);
    }
    putchar('"');
}

/* Report that the test cannot produce a measurement here, and stop. */
__attribute__((noreturn, format(printf, 1, 2))) static void unavailable(const char *format, ...)
{
    char reason[512];
    va_list args;
    va_start(args, format);
    vsnprintf(reason, sizeof reason, format, args);
    va_end(args);
    printf("EMU-RESULT: {\"area\": \"graphics\", \"test\": \"%s_fps\", \"technology\": \"%s\", "
           "\"unit\": \"frames/s\", \"value\": null, \"unavailable\": ", test_name, test_name);
    json_string(reason);
    printf("}\n");
    fflush(stdout);
    exit(3);
}

static int is_software_renderer(const char *name)
{
    return name && (strstr(name, "llvmpipe") || strstr(name, "softpipe") || strstr(name, "swrast") ||
                    strstr(name, "SwiftShader") || strstr(name, "Software"));
}

/* ------------------------------------------------------------- window --- */

struct window {
    struct wl_display *display;
    struct wl_compositor *compositor;
    struct wl_shm *shm;
    struct xdg_wm_base *wm_base;
    struct wp_presentation *presentation;
    struct wl_surface *surface;
    struct xdg_surface *xdg_surface;
    struct xdg_toplevel *toplevel;
    int width, height;
    int configured, closed;
    long submitted;  /* frames handed to the compositor */
    long presented;  /* frames the compositor reported as shown on the display */
    long last_shown; /* number of the newest frame shown */
};

static void registry_global(void *data, struct wl_registry *registry, uint32_t name, const char *interface,
                            uint32_t version)
{
    struct window *w = data;
    if (!strcmp(interface, wl_compositor_interface.name))
        w->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, version < 4 ? version : 4);
    else if (!strcmp(interface, wl_shm_interface.name))
        w->shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
    else if (!strcmp(interface, xdg_wm_base_interface.name))
        w->wm_base = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
    else if (!strcmp(interface, wp_presentation_interface.name))
        w->presentation = wl_registry_bind(registry, name, &wp_presentation_interface, 1);
}

static void registry_global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
    (void)data, (void)registry, (void)name;
}

static const struct wl_registry_listener registry_listener = {registry_global, registry_global_remove};

static void wm_base_ping(void *data, struct xdg_wm_base *wm_base, uint32_t serial)
{
    (void)data;
    xdg_wm_base_pong(wm_base, serial);
}

static const struct xdg_wm_base_listener wm_base_listener = {wm_base_ping};

static void xdg_surface_configure(void *data, struct xdg_surface *xdg_surface, uint32_t serial)
{
    struct window *w = data;
    xdg_surface_ack_configure(xdg_surface, serial);
    w->configured = 1;
}

static const struct xdg_surface_listener xdg_surface_listener = {xdg_surface_configure};

static void toplevel_configure(void *data, struct xdg_toplevel *toplevel, int32_t width, int32_t height,
                               struct wl_array *states)
{
    struct window *w = data;
    (void)toplevel, (void)states;
    /* The size is fixed once rendering has started. */
    if (width > 0 && height > 0 && !w->submitted) {
        w->width = width;
        w->height = height;
    }
}

static void toplevel_close(void *data, struct xdg_toplevel *toplevel)
{
    (void)toplevel;
    ((struct window *)data)->closed = 1;
}

static const struct xdg_toplevel_listener toplevel_listener = {.configure = toplevel_configure,
                                                               .close = toplevel_close};

/* Read and dispatch what the compositor sent, waiting up to timeout_ms. */
static void pump(struct window *w, int timeout_ms)
{
    while (wl_display_prepare_read(w->display) != 0)
        if (wl_display_dispatch_pending(w->display) < 0)
            unavailable("lost the connection to the Wayland compositor");
    wl_display_flush(w->display);
    struct pollfd fd = {wl_display_get_fd(w->display), POLLIN, 0};
    if (poll(&fd, 1, timeout_ms) > 0)
        wl_display_read_events(w->display);
    else
        wl_display_cancel_read(w->display);
    if (wl_display_dispatch_pending(w->display) < 0)
        unavailable("lost the connection to the Wayland compositor");
}

static void open_window(struct window *w)
{
    memset(w, 0, sizeof *w);
    w->display = wl_display_connect(NULL);
    if (!w->display)
        unavailable("cannot connect to a Wayland compositor (WAYLAND_DISPLAY=%s): %s",
                    getenv("WAYLAND_DISPLAY") ? getenv("WAYLAND_DISPLAY") : "unset", strerror(errno));
    struct wl_registry *registry = wl_display_get_registry(w->display);
    wl_registry_add_listener(registry, &registry_listener, w);
    wl_display_roundtrip(w->display);
    if (!w->compositor || !w->shm || !w->wm_base)
        unavailable("the Wayland compositor lacks wl_compositor, wl_shm or xdg_wm_base");
    xdg_wm_base_add_listener(w->wm_base, &wm_base_listener, w);

    w->surface = wl_compositor_create_surface(w->compositor);
    w->xdg_surface = xdg_wm_base_get_xdg_surface(w->wm_base, w->surface);
    xdg_surface_add_listener(w->xdg_surface, &xdg_surface_listener, w);
    w->toplevel = xdg_surface_get_toplevel(w->xdg_surface);
    xdg_toplevel_add_listener(w->toplevel, &toplevel_listener, w);
    xdg_toplevel_set_title(w->toplevel, "emugfx");
    xdg_toplevel_set_app_id(w->toplevel, "emugfx");
    xdg_toplevel_set_fullscreen(w->toplevel, NULL);
    wl_surface_commit(w->surface);
    while (!w->configured)
        if (wl_display_dispatch(w->display) < 0)
            unavailable("lost the connection to the Wayland compositor");
    if (w->width <= 0 || w->height <= 0)
        unavailable("the Wayland compositor did not give the window a size");
    struct wl_region *opaque = wl_compositor_create_region(w->compositor);
    wl_region_add(opaque, 0, 0, w->width, w->height);
    wl_surface_set_opaque_region(w->surface, opaque);
    wl_region_destroy(opaque);
}

struct feedback_tag {
    struct window *window;
    long frame;
};

static void feedback_sync_output(void *data, struct wp_presentation_feedback *feedback, struct wl_output *output)
{
    (void)data, (void)feedback, (void)output;
}

static void feedback_presented(void *data, struct wp_presentation_feedback *feedback, uint32_t sec_hi,
                               uint32_t sec_lo, uint32_t nsec, uint32_t refresh, uint32_t seq_hi, uint32_t seq_lo,
                               uint32_t flags)
{
    struct feedback_tag *tag = data;
    (void)sec_hi, (void)sec_lo, (void)nsec, (void)refresh, (void)seq_hi, (void)seq_lo, (void)flags;
    tag->window->presented++;
    if (tag->frame > tag->window->last_shown)
        tag->window->last_shown = tag->frame;
    wp_presentation_feedback_destroy(feedback);
    free(tag);
}

static void feedback_discarded(void *data, struct wp_presentation_feedback *feedback)
{
    wp_presentation_feedback_destroy(feedback);
    free(data);
}

static const struct wp_presentation_feedback_listener feedback_listener = {feedback_sync_output, feedback_presented,
                                                                           feedback_discarded};

/* Call just before the commit that submits a frame. */
static void track_frame(struct window *w)
{
    w->submitted++;
    if (!w->presentation)
        return;
    struct feedback_tag *tag = malloc(sizeof *tag);
    tag->window = w;
    tag->frame = w->submitted;
    wp_presentation_feedback_add_listener(wp_presentation_feedback(w->presentation, w->surface),
                                          &feedback_listener, tag);
}

/* Wait until the last submitted frame is on the display. */
static int settle(struct window *w)
{
    double deadline = now() + 120.0;
    if (!w->presentation) {
        wl_display_roundtrip(w->display);
        usleep(500000);
        return 0;
    }
    while (w->last_shown < w->submitted && now() < deadline)
        pump(w, 100);
    return w->last_shown >= w->submitted;
}

/* -------------------------------------------------------------- scene --- */

/* The animation parameter wraps where every motion in the scene repeats. */
static double scene_time(long frame)
{
    return fmod((double)frame * 0.02, 20.0 * PI);
}

struct vertex {
    float x, y, r, g, b, a;
};

/* NQUADS translucent squares that orbit and spin, as two triangles each. */
static void build_quads(struct vertex *out, long frame, int width, int height)
{
    double t = scene_time(frame);
    double aspect = (double)height / (double)width;
    static const int corner[6] = {0, 1, 2, 0, 2, 3};
    static const double lx[4] = {-1, 1, 1, -1}, ly[4] = {-1, -1, 1, 1};
    for (int i = 0; i < NQUADS; i++) {
        double cx = 0.82 * sin(t * (0.5 + 0.5 * (i % 4)) + i * 0.7);
        double cy = 0.70 * cos(t * (0.5 + 0.5 * ((i / 4) % 3)) + i * 1.3);
        double angle = t * (1 + i % 5) + i;
        double half = 0.05 + 0.02 * (i % 3);
        double c = cos(angle) * half, s = sin(angle) * half;
        float r = (float)(0.5 + 0.5 * sin(i * 0.9));
        float g = (float)(0.5 + 0.5 * sin(i * 1.7 + 2.0));
        float b = (float)(0.5 + 0.5 * sin(i * 2.3 + 4.0));
        for (int k = 0; k < 6; k++) {
            int n = corner[k];
            struct vertex *v = &out[i * 6 + k];
            v->x = (float)(cx + (lx[n] * c - ly[n] * s) * aspect);
            v->y = (float)(cy + lx[n] * s + ly[n] * c);
            v->r = r, v->g = g, v->b = b, v->a = 0.6f;
        }
    }
}

struct block {
    int x, y, width, height; /* top-left origin */
    struct rgb color;
};

static void marker_blocks(struct block out[5], int width, int height, struct rgb technology)
{
    int s = height / 12;
    out[0] = (struct block){0, 0, s, s, CORNER[0]};
    out[1] = (struct block){width - s, 0, s, s, CORNER[1]};
    out[2] = (struct block){0, height - s, s, s, CORNER[2]};
    out[3] = (struct block){width - s, height - s, s, s, CORNER[3]};
    out[4] = (struct block){width / 2 - s, 0, 2 * s, s, technology};
}

/* -------------------------------------------------------------- stats --- */

struct stats {
    double *frame_seconds;
    long count, capacity;
    double first_frame; /* from process start until the first frame was submitted */
    double begin, end;
    long presented_at_begin, presented_at_end;
};

static void stats_add(struct stats *s, double seconds)
{
    if (s->count == s->capacity) {
        s->capacity = s->capacity ? s->capacity * 2 : 4096;
        s->frame_seconds = realloc(s->frame_seconds, (size_t)s->capacity * sizeof(double));
        if (!s->frame_seconds)
            unavailable("out of memory");
    }
    s->frame_seconds[s->count++] = seconds;
}

static int compare_doubles(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

static double percentile(const struct stats *s, double fraction)
{
    long index = (long)ceil(fraction * (double)s->count) - 1;
    if (index < 0)
        index = 0;
    if (index >= s->count)
        index = s->count - 1;
    return s->frame_seconds[index];
}

/* Bookkeeping after each submitted frame; returns 1 when the test is over. */
static int frame_done(struct window *w, struct stats *s, double *previous)
{
    double t = now();
    if (w->submitted == 1) {
        s->first_frame = t - process_start;
        s->begin = t;
        s->presented_at_begin = w->presented;
    } else {
        stats_add(s, t - *previous);
    }
    *previous = t;
    pump(w, 0);
    if (w->closed)
        unavailable("the compositor closed the window");
    if (w->submitted >= 2 && t - s->begin >= opt_seconds) {
        s->end = t;
        s->presented_at_end = w->presented;
        return 1;
    }
    return 0;
}

static void report(struct window *w, struct stats *s, const char *renderer, const char *api, int accelerated,
                   const char *present_mode, struct rgb marker)
{
    double elapsed = s->end - s->begin;
    double total = 0;
    for (long i = 0; i < s->count; i++)
        total += s->frame_seconds[i];
    qsort(s->frame_seconds, (size_t)s->count, sizeof(double), compare_doubles);
    int shown = settle(w);

    printf("EMU-RESULT: {\"area\": \"graphics\", \"test\": \"%s_fps\", \"technology\": \"%s\", "
           "\"unit\": \"frames/s\", \"value\": %.2f, \"resolution\": \"%dx%d\", \"frames\": %ld, "
           "\"seconds\": %.3f, \"frame_time_ms\": {\"mean\": %.3f, \"p50\": %.3f, \"p99\": %.3f, \"max\": %.3f}, "
           "\"first_frame_seconds\": %.3f, ",
           test_name, test_name, (double)s->count / elapsed, w->width, w->height, s->count, elapsed,
           total / (double)s->count * 1e3, percentile(s, 0.50) * 1e3, percentile(s, 0.99) * 1e3,
           s->frame_seconds[s->count - 1] * 1e3, s->first_frame);
    if (w->presentation)
        printf("\"displayed_fps\": %.2f, ", (double)(s->presented_at_end - s->presented_at_begin) / elapsed);
    else
        printf("\"displayed_fps\": null, ");
    printf("\"renderer\": ");
    json_string(renderer);
    printf(", \"api\": ");
    json_string(api);
    printf(", \"accelerated\": %s", accelerated ? "true" : "false");
    if (present_mode)
        printf(", \"present_mode\": \"%s\"", present_mode);
    printf("}\n");
    fflush(stdout);

    if (opt_hold > 0) {
        printf("EMU-SCREEN: {\"test\": \"%s_fps\", \"technology\": \"%s\", \"width\": %d, \"height\": %d, "
               "\"marker\": [%d, %d, %d], \"on_display\": %s}\n",
               test_name, test_name, w->width, w->height, marker.r, marker.g, marker.b, shown ? "true" : "false");
        fflush(stdout);
        double until = now() + opt_hold;
        while (now() < until && !w->closed)
            pump(w, 50);
    }
}

/* ------------------------------------------------- wayland (wl_shm) --- */

struct shm_buffer {
    struct wl_buffer *buffer;
    uint32_t *pixels;
    int busy;
};

static void buffer_release(void *data, struct wl_buffer *buffer)
{
    (void)buffer;
    ((struct shm_buffer *)data)->busy = 0;
}

static const struct wl_buffer_listener buffer_listener = {buffer_release};

static void fill_block(uint32_t *pixels, int width, const struct block *b)
{
    uint32_t value = 0xff000000u | ((uint32_t)b->color.r << 16) | ((uint32_t)b->color.g << 8) | b->color.b;
    for (int y = b->y; y < b->y + b->height; y++) {
        uint32_t *row = pixels + (size_t)y * (size_t)width + b->x;
        for (int x = 0; x < b->width; x++)
            row[x] = value;
    }
}

static void draw_cpu(uint32_t *pixels, uint32_t *column, int width, int height, long frame)
{
    /* Background: a colour gradient that scrolls with the frame number. */
    for (int x = 0; x < width; x++)
        column[x] = (uint32_t)(((long)x * 256 / width + frame * 2) & 255) << 16;
    for (int y = 0; y < height; y++) {
        uint32_t base = 0xff000000u | (uint32_t)(((long)y * 256 / height + frame) & 255) << 8 |
                        (uint32_t)((frame * 3) & 255);
        uint32_t *row = pixels + (size_t)y * (size_t)width;
        for (int x = 0; x < width; x++)
            row[x] = base | column[x];
    }
    /* Translucent rectangles on fixed orbits, blended half and half. */
    double t = scene_time(frame);
    int rect_w = width / 8, rect_h = height / 8;
    for (int i = 0; i < 16; i++) {
        int cx = (int)((0.5 + 0.4 * sin(t * (0.5 + 0.5 * (i % 4)) + i * 0.7)) * width);
        int cy = (int)((0.5 + 0.4 * cos(t * (0.5 + 0.5 * ((i / 4) % 3)) + i * 1.3)) * height);
        int x0 = cx - rect_w / 2, y0 = cy - rect_h / 2;
        int x1 = x0 + rect_w, y1 = y0 + rect_h;
        if (x0 < 0) x0 = 0;
        if (y0 < 0) y0 = 0;
        if (x1 > width) x1 = width;
        if (y1 > height) y1 = height;
        uint32_t half = ((0x202020u * (uint32_t)(i + 1)) >> 1) & 0x7f7f7fu;
        for (int y = y0; y < y1; y++) {
            uint32_t *row = pixels + (size_t)y * (size_t)width;
            for (int x = x0; x < x1; x++)
                row[x] = 0xff000000u | (((row[x] >> 1) & 0x7f7f7fu) + half);
        }
    }
    struct block blocks[5];
    marker_blocks(blocks, width, height, MARK_WAYLAND);
    for (int i = 0; i < 5; i++)
        fill_block(pixels, width, &blocks[i]);
}

static void run_wayland(void)
{
    struct window w;
    open_window(&w);
    enum { BUFFERS = 3 };
    size_t frame_bytes = (size_t)w.width * (size_t)w.height * 4;
    int fd = memfd_create("emugfx", MFD_CLOEXEC);
    if (fd < 0 || ftruncate(fd, (off_t)(frame_bytes * BUFFERS)) < 0)
        unavailable("cannot allocate shared memory for %dx%d buffers: %s", w.width, w.height, strerror(errno));
    uint8_t *memory = mmap(NULL, frame_bytes * BUFFERS, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (memory == MAP_FAILED)
        unavailable("cannot map shared memory: %s", strerror(errno));
    struct wl_shm_pool *pool = wl_shm_create_pool(w.shm, fd, (int32_t)(frame_bytes * BUFFERS));
    struct shm_buffer buffers[BUFFERS];
    for (int i = 0; i < BUFFERS; i++) {
        buffers[i].buffer = wl_shm_pool_create_buffer(pool, (int32_t)(frame_bytes * (size_t)i), w.width, w.height,
                                                      w.width * 4, WL_SHM_FORMAT_XRGB8888);
        buffers[i].pixels = (uint32_t *)(memory + frame_bytes * (size_t)i);
        buffers[i].busy = 0;
        wl_buffer_add_listener(buffers[i].buffer, &buffer_listener, &buffers[i]);
    }
    uint32_t *column = malloc((size_t)w.width * sizeof(uint32_t));
    int damage_buffer = wl_proxy_get_version((struct wl_proxy *)w.surface) >= 4;

    struct stats stats = {0};
    double previous = 0;
    for (long frame = 0;; frame++) {
        struct shm_buffer *target = NULL;
        while (!target) {
            for (int i = 0; i < BUFFERS && !target; i++)
                if (!buffers[i].busy)
                    target = &buffers[i];
            if (!target)
                pump(&w, -1); /* the compositor still holds every buffer */
        }
        draw_cpu(target->pixels, column, w.width, w.height, frame);
        wl_surface_attach(w.surface, target->buffer, 0, 0);
        if (damage_buffer)
            wl_surface_damage_buffer(w.surface, 0, 0, w.width, w.height);
        else
            wl_surface_damage(w.surface, 0, 0, w.width, w.height);
        track_frame(&w);
        wl_surface_commit(w.surface);
        target->busy = 1;
        if (frame_done(&w, &stats, &previous))
            break;
    }
    report(&w, &stats, "cpu", "wl_shm XRGB8888", 0, NULL, MARK_WAYLAND);
}

/* --------------------------------------------------------- OpenGL ES --- */

static const char *GLES_BACKGROUND_VS =
    "attribute vec2 pos;\n"
    "varying vec2 uv;\n"
    "void main() { uv = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }\n";

/* Kept identical to target/src/shaders/background.frag. */
static const char *GLES_BACKGROUND_FS =
    "#ifdef GL_FRAGMENT_PRECISION_HIGH\n"
    "precision highp float;\n"
    "#else\n"
    "precision mediump float;\n"
    "#endif\n"
    "varying vec2 uv;\n"
    "uniform float t;\n"
    "void main() {\n"
    "    vec3 col = 0.5 + 0.5 * cos(t + uv.xyx * vec3(6.0, 4.0, 3.0) + vec3(0.0, 2.0, 4.0));\n"
    "    float v = sin(uv.x * 20.0 + t) + sin(uv.y * 14.0 - t * 1.5) + sin((uv.x + uv.y) * 9.0 + t * 0.5);\n"
    "    col *= 0.75 + 0.25 * sin(v * 3.14159265);\n"
    "    gl_FragColor = vec4(col, 1.0);\n"
    "}\n";

static const char *GLES_QUAD_VS =
    "attribute vec2 pos;\n"
    "attribute vec4 color;\n"
    "varying vec4 vcolor;\n"
    "void main() { vcolor = color; gl_Position = vec4(pos, 0.0, 1.0); }\n";

static const char *GLES_QUAD_FS =
    "precision mediump float;\n"
    "varying vec4 vcolor;\n"
    "void main() { gl_FragColor = vcolor; }\n";

static GLuint gles_shader(GLenum type, const char *source)
{
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &source, NULL);
    glCompileShader(shader);
    GLint ok = 0;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[256] = "";
        glGetShaderInfoLog(shader, sizeof log, NULL, log);
        unavailable("an OpenGL ES shader did not compile: %s", log);
    }
    return shader;
}

static GLuint gles_program(const char *vs, const char *fs, const char *attribute0, const char *attribute1)
{
    GLuint program = glCreateProgram();
    glAttachShader(program, gles_shader(GL_VERTEX_SHADER, vs));
    glAttachShader(program, gles_shader(GL_FRAGMENT_SHADER, fs));
    glBindAttribLocation(program, 0, attribute0);
    if (attribute1)
        glBindAttribLocation(program, 1, attribute1);
    glLinkProgram(program);
    GLint ok = 0;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (!ok)
        unavailable("an OpenGL ES program did not link");
    return program;
}

struct gles {
    EGLDisplay display;
    EGLSurface surface;
    EGLContext context;
    struct wl_egl_window *native;
    char renderer[160], version[160];
};

static void gles_open(struct window *w, struct gles *g)
{
    g->display = eglGetDisplay((EGLNativeDisplayType)w->display);
    if (g->display == EGL_NO_DISPLAY || !eglInitialize(g->display, NULL, NULL))
        unavailable("EGL did not initialise on the Wayland display (error 0x%x)", eglGetError());
    if (!eglBindAPI(EGL_OPENGL_ES_API))
        unavailable("EGL has no OpenGL ES API here");
    static const EGLint config_attributes[] = {EGL_SURFACE_TYPE, EGL_WINDOW_BIT, EGL_RENDERABLE_TYPE,
                                               EGL_OPENGL_ES2_BIT, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8,
                                               EGL_BLUE_SIZE, 8, EGL_NONE};
    EGLConfig configs[64], config = NULL;
    EGLint count = 0;
    if (!eglChooseConfig(g->display, config_attributes, configs, 64, &count) || count < 1)
        unavailable("EGL offers no 8-bit RGB OpenGL ES 2 window configuration");
    /* Prefer a configuration without alpha: the window is opaque. */
    for (EGLint i = 0; i < count && !config; i++) {
        EGLint alpha = 0;
        eglGetConfigAttrib(g->display, configs[i], EGL_ALPHA_SIZE, &alpha);
        if (alpha == 0)
            config = configs[i];
    }
    if (!config)
        config = configs[0];
    static const EGLint context_attributes[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
    g->context = eglCreateContext(g->display, config, EGL_NO_CONTEXT, context_attributes);
    if (g->context == EGL_NO_CONTEXT)
        unavailable("EGL could not create an OpenGL ES 2 context (error 0x%x)", eglGetError());
    g->native = wl_egl_window_create(w->surface, w->width, w->height);
    g->surface = eglCreateWindowSurface(g->display, config, (EGLNativeWindowType)g->native, NULL);
    if (g->surface == EGL_NO_SURFACE)
        unavailable("EGL could not create a window surface (error 0x%x)", eglGetError());
    if (!eglMakeCurrent(g->display, g->surface, g->surface, g->context))
        unavailable("EGL could not make the context current (error 0x%x)", eglGetError());
    eglSwapInterval(g->display, 0); /* do not wait for the display's refresh */
    snprintf(g->renderer, sizeof g->renderer, "%s", (const char *)glGetString(GL_RENDERER));
    snprintf(g->version, sizeof g->version, "%s", (const char *)glGetString(GL_VERSION));
}

static void run_gles(void)
{
    struct window w;
    struct gles g;
    open_window(&w);
    gles_open(&w, &g);

    GLuint background = gles_program(GLES_BACKGROUND_VS, GLES_BACKGROUND_FS, "pos", NULL);
    GLuint quads = gles_program(GLES_QUAD_VS, GLES_QUAD_FS, "pos", "color");
    GLint time_uniform = glGetUniformLocation(background, "t");
    static const float triangle[6] = {-1, -1, 3, -1, -1, 3}; /* one triangle that covers the screen */
    static struct vertex vertices[QUAD_VERTICES];
    struct block blocks[5];
    marker_blocks(blocks, w.width, w.height, MARK_GLES);
    glViewport(0, 0, w.width, w.height);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    struct stats stats = {0};
    double previous = 0;
    for (long frame = 0;; frame++) {
        glDisable(GL_SCISSOR_TEST);
        glDisable(GL_BLEND);
        glUseProgram(background);
        glUniform1f(time_uniform, (float)scene_time(frame));
        glEnableVertexAttribArray(0);
        glDisableVertexAttribArray(1);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, triangle);
        glDrawArrays(GL_TRIANGLES, 0, 3);

        build_quads(vertices, frame, w.width, w.height);
        glEnable(GL_BLEND);
        glUseProgram(quads);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(struct vertex), &vertices[0].x);
        glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, sizeof(struct vertex), &vertices[0].r);
        glDrawArrays(GL_TRIANGLES, 0, QUAD_VERTICES);

        glEnable(GL_SCISSOR_TEST);
        for (int i = 0; i < 5; i++) {
            const struct block *b = &blocks[i];
            glScissor(b->x, w.height - b->y - b->height, b->width, b->height); /* GL counts rows from the bottom */
            glClearColor(b->color.r / 255.0f, b->color.g / 255.0f, b->color.b / 255.0f, 1.0f);
            glClear(GL_COLOR_BUFFER_BIT);
        }
        glFinish(); /* the frame is complete before it counts */
        track_frame(&w);
        if (!eglSwapBuffers(g.display, g.surface))
            unavailable("eglSwapBuffers failed (error 0x%x)", eglGetError());
        if (frame_done(&w, &stats, &previous))
            break;
    }
    report(&w, &stats, g.renderer, g.version, !is_software_renderer(g.renderer), NULL, MARK_GLES);
}

/* ------------------------------------------------------------- Vulkan --- */

#define VK_CHECK(call)                                                          \
    do {                                                                        \
        VkResult result_ = (call);                                              \
        if (result_ != VK_SUCCESS)                                              \
            unavailable("Vulkan: %s returned %d", #call, (int)result_);         \
    } while (0)

struct vulkan {
    VkInstance instance;
    VkPhysicalDevice physical;
    VkPhysicalDeviceProperties properties;
    VkSurfaceKHR surface;
    uint32_t queue_family;
};

static int vulkan_device_rank(VkPhysicalDeviceType type)
{
    switch (type) {
    case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU: return 4;
    case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU: return 3;
    case VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU: return 2;
    case VK_PHYSICAL_DEVICE_TYPE_CPU: return 0;
    default: return 1;
    }
}

static const char *vulkan_device_type(VkPhysicalDeviceType type)
{
    switch (type) {
    case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU: return "discrete GPU";
    case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU: return "integrated GPU";
    case VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU: return "virtual GPU";
    case VK_PHYSICAL_DEVICE_TYPE_CPU: return "CPU";
    default: return "other";
    }
}

/* Create the instance and choose the device: a GPU when there is one that
 * can present to the window, otherwise a CPU implementation. */
static void vulkan_open(struct window *w, struct vulkan *v)
{
    static const char *extensions[] = {VK_KHR_SURFACE_EXTENSION_NAME, VK_KHR_WAYLAND_SURFACE_EXTENSION_NAME};
    VkApplicationInfo application = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
                                     .pApplicationName = "emugfx",
                                     .apiVersion = VK_API_VERSION_1_0};
    VkInstanceCreateInfo instance_info = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
                                          .pApplicationInfo = &application,
                                          .enabledExtensionCount = 2,
                                          .ppEnabledExtensionNames = extensions};
    VK_CHECK(vkCreateInstance(&instance_info, NULL, &v->instance));
    VkWaylandSurfaceCreateInfoKHR surface_info = {.sType = VK_STRUCTURE_TYPE_WAYLAND_SURFACE_CREATE_INFO_KHR,
                                                  .display = w->display,
                                                  .surface = w->surface};
    VK_CHECK(vkCreateWaylandSurfaceKHR(v->instance, &surface_info, NULL, &v->surface));

    VkPhysicalDevice devices[16];
    uint32_t device_count = 16;
    vkEnumeratePhysicalDevices(v->instance, &device_count, devices);
    int best = -1;
    for (uint32_t i = 0; i < device_count; i++) {
        VkPhysicalDeviceProperties properties;
        vkGetPhysicalDeviceProperties(devices[i], &properties);
        VkQueueFamilyProperties families[32];
        uint32_t family_count = 32;
        vkGetPhysicalDeviceQueueFamilyProperties(devices[i], &family_count, families);
        for (uint32_t f = 0; f < family_count; f++) {
            VkBool32 can_present = VK_FALSE;
            vkGetPhysicalDeviceSurfaceSupportKHR(devices[i], f, v->surface, &can_present);
            if (!(families[f].queueFlags & VK_QUEUE_GRAPHICS_BIT) || !can_present)
                continue;
            if (vulkan_device_rank(properties.deviceType) > best) {
                best = vulkan_device_rank(properties.deviceType);
                v->physical = devices[i];
                v->properties = properties;
                v->queue_family = f;
            }
            break;
        }
    }
    if (best < 0)
        unavailable("no Vulkan device can present to the Wayland display (%u devices found)", device_count);
}

static VkShaderModule vulkan_shader(VkDevice device, const uint32_t *code, size_t bytes)
{
    VkShaderModuleCreateInfo info = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
                                     .codeSize = bytes,
                                     .pCode = code};
    VkShaderModule module;
    VK_CHECK(vkCreateShaderModule(device, &info, NULL, &module));
    return module;
}

static VkPipeline vulkan_pipeline(VkDevice device, VkRenderPass render_pass, VkPipelineLayout layout,
                                  VkExtent2D extent, VkShaderModule vertex, VkShaderModule fragment,
                                  int with_vertices)
{
    VkPipelineShaderStageCreateInfo stages[2] = {
        {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
         .stage = VK_SHADER_STAGE_VERTEX_BIT,
         .module = vertex,
         .pName = "main"},
        {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
         .stage = VK_SHADER_STAGE_FRAGMENT_BIT,
         .module = fragment,
         .pName = "main"}};
    VkVertexInputBindingDescription binding = {.binding = 0,
                                               .stride = sizeof(struct vertex),
                                               .inputRate = VK_VERTEX_INPUT_RATE_VERTEX};
    VkVertexInputAttributeDescription attributes[2] = {
        {.location = 0, .binding = 0, .format = VK_FORMAT_R32G32_SFLOAT, .offset = offsetof(struct vertex, x)},
        {.location = 1, .binding = 0, .format = VK_FORMAT_R32G32B32A32_SFLOAT, .offset = offsetof(struct vertex, r)}};
    VkPipelineVertexInputStateCreateInfo vertex_input = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO,
        .vertexBindingDescriptionCount = with_vertices ? 1 : 0,
        .pVertexBindingDescriptions = &binding,
        .vertexAttributeDescriptionCount = with_vertices ? 2 : 0,
        .pVertexAttributeDescriptions = attributes};
    VkPipelineInputAssemblyStateCreateInfo assembly = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,
        .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
    VkViewport viewport = {0, 0, (float)extent.width, (float)extent.height, 0, 1};
    VkRect2D scissor = {{0, 0}, extent};
    VkPipelineViewportStateCreateInfo viewport_state = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,
        .viewportCount = 1,
        .pViewports = &viewport,
        .scissorCount = 1,
        .pScissors = &scissor};
    VkPipelineRasterizationStateCreateInfo raster = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,
        .polygonMode = VK_POLYGON_MODE_FILL,
        .cullMode = VK_CULL_MODE_NONE,
        .frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE,
        .lineWidth = 1.0f};
    VkPipelineMultisampleStateCreateInfo multisample = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,
        .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT};
    VkPipelineColorBlendAttachmentState blend_attachment = {
        .blendEnable = with_vertices ? VK_TRUE : VK_FALSE,
        .srcColorBlendFactor = VK_BLEND_FACTOR_SRC_ALPHA,
        .dstColorBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
        .colorBlendOp = VK_BLEND_OP_ADD,
        .srcAlphaBlendFactor = VK_BLEND_FACTOR_SRC_ALPHA,
        .dstAlphaBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
        .alphaBlendOp = VK_BLEND_OP_ADD,
        .colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT |
                          VK_COLOR_COMPONENT_A_BIT};
    VkPipelineColorBlendStateCreateInfo blend = {.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
                                                 .attachmentCount = 1,
                                                 .pAttachments = &blend_attachment};
    VkGraphicsPipelineCreateInfo info = {.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,
                                         .stageCount = 2,
                                         .pStages = stages,
                                         .pVertexInputState = &vertex_input,
                                         .pInputAssemblyState = &assembly,
                                         .pViewportState = &viewport_state,
                                         .pRasterizationState = &raster,
                                         .pMultisampleState = &multisample,
                                         .pColorBlendState = &blend,
                                         .layout = layout,
                                         .renderPass = render_pass};
    VkPipeline pipeline;
    VK_CHECK(vkCreateGraphicsPipelines(device, VK_NULL_HANDLE, 1, &info, NULL, &pipeline));
    return pipeline;
}

static void run_vulkan(void)
{
    struct window w;
    struct vulkan v;
    open_window(&w);
    vulkan_open(&w, &v);

    float priority = 1.0f;
    VkDeviceQueueCreateInfo queue_info = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
                                          .queueFamilyIndex = v.queue_family,
                                          .queueCount = 1,
                                          .pQueuePriorities = &priority};
    static const char *device_extensions[] = {VK_KHR_SWAPCHAIN_EXTENSION_NAME};
    VkDeviceCreateInfo device_info = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
                                      .queueCreateInfoCount = 1,
                                      .pQueueCreateInfos = &queue_info,
                                      .enabledExtensionCount = 1,
                                      .ppEnabledExtensionNames = device_extensions};
    VkDevice device;
    VK_CHECK(vkCreateDevice(v.physical, &device_info, NULL, &device));
    VkQueue queue;
    vkGetDeviceQueue(device, v.queue_family, 0, &queue);

    /* Swapchain: an 8-bit format without sRGB encoding, so marker colours
     * reach the display unchanged, and a mode that does not wait for the
     * display's refresh when there is one. */
    VkSurfaceCapabilitiesKHR capabilities;
    VK_CHECK(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(v.physical, v.surface, &capabilities));
    VkSurfaceFormatKHR formats[64];
    uint32_t format_count = 64;
    vkGetPhysicalDeviceSurfaceFormatsKHR(v.physical, v.surface, &format_count, formats);
    if (!format_count)
        unavailable("the Vulkan device offers no surface format");
    VkSurfaceFormatKHR format = formats[0];
    for (uint32_t i = 0; i < format_count; i++)
        if (formats[i].format == VK_FORMAT_B8G8R8A8_UNORM || formats[i].format == VK_FORMAT_R8G8B8A8_UNORM) {
            format = formats[i];
            break;
        }
    VkPresentModeKHR modes[16];
    uint32_t mode_count = 16;
    vkGetPhysicalDeviceSurfacePresentModesKHR(v.physical, v.surface, &mode_count, modes);
    VkPresentModeKHR present_mode = VK_PRESENT_MODE_FIFO_KHR;
    const char *present_mode_name = "fifo";
    for (uint32_t i = 0; i < mode_count; i++)
        if (modes[i] == VK_PRESENT_MODE_MAILBOX_KHR) {
            present_mode = modes[i];
            present_mode_name = "mailbox";
        }
    for (uint32_t i = 0; i < mode_count && present_mode == VK_PRESENT_MODE_FIFO_KHR; i++)
        if (modes[i] == VK_PRESENT_MODE_IMMEDIATE_KHR) {
            present_mode = modes[i];
            present_mode_name = "immediate";
        }
    VkExtent2D extent = capabilities.currentExtent;
    if (extent.width == UINT32_MAX) {
        extent.width = (uint32_t)w.width;
        extent.height = (uint32_t)w.height;
    }
    uint32_t image_count = capabilities.minImageCount < 3 ? 3 : capabilities.minImageCount;
    if (capabilities.maxImageCount && image_count > capabilities.maxImageCount)
        image_count = capabilities.maxImageCount;
    VkCompositeAlphaFlagBitsKHR alpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    if (!(capabilities.supportedCompositeAlpha & alpha))
        alpha = (VkCompositeAlphaFlagBitsKHR)(capabilities.supportedCompositeAlpha &
                                              -capabilities.supportedCompositeAlpha);
    VkSwapchainCreateInfoKHR swapchain_info = {.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,
                                               .surface = v.surface,
                                               .minImageCount = image_count,
                                               .imageFormat = format.format,
                                               .imageColorSpace = format.colorSpace,
                                               .imageExtent = extent,
                                               .imageArrayLayers = 1,
                                               .imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT,
                                               .imageSharingMode = VK_SHARING_MODE_EXCLUSIVE,
                                               .preTransform = capabilities.currentTransform,
                                               .compositeAlpha = alpha,
                                               .presentMode = present_mode,
                                               .clipped = VK_TRUE};
    VkSwapchainKHR swapchain;
    VK_CHECK(vkCreateSwapchainKHR(device, &swapchain_info, NULL, &swapchain));
    VkImage images[16];
    image_count = 16;
    VK_CHECK(vkGetSwapchainImagesKHR(device, swapchain, &image_count, images));

    VkAttachmentDescription attachment = {.format = format.format,
                                          .samples = VK_SAMPLE_COUNT_1_BIT,
                                          .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR,
                                          .storeOp = VK_ATTACHMENT_STORE_OP_STORE,
                                          .stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE,
                                          .stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE,
                                          .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
                                          .finalLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR};
    VkAttachmentReference color_reference = {0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
    VkSubpassDescription subpass = {.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS,
                                    .colorAttachmentCount = 1,
                                    .pColorAttachments = &color_reference};
    VkSubpassDependency dependency = {.srcSubpass = VK_SUBPASS_EXTERNAL,
                                      .dstSubpass = 0,
                                      .srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                                      .dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                                      .dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT};
    VkRenderPassCreateInfo render_pass_info = {.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO,
                                               .attachmentCount = 1,
                                               .pAttachments = &attachment,
                                               .subpassCount = 1,
                                               .pSubpasses = &subpass,
                                               .dependencyCount = 1,
                                               .pDependencies = &dependency};
    VkRenderPass render_pass;
    VK_CHECK(vkCreateRenderPass(device, &render_pass_info, NULL, &render_pass));

    VkFramebuffer framebuffers[16];
    for (uint32_t i = 0; i < image_count; i++) {
        VkImageViewCreateInfo view_info = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
                                           .image = images[i],
                                           .viewType = VK_IMAGE_VIEW_TYPE_2D,
                                           .format = format.format,
                                           .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
        VkImageView view;
        VK_CHECK(vkCreateImageView(device, &view_info, NULL, &view));
        VkFramebufferCreateInfo framebuffer_info = {.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO,
                                                    .renderPass = render_pass,
                                                    .attachmentCount = 1,
                                                    .pAttachments = &view,
                                                    .width = extent.width,
                                                    .height = extent.height,
                                                    .layers = 1};
        VK_CHECK(vkCreateFramebuffer(device, &framebuffer_info, NULL, &framebuffers[i]));
    }

    VkPushConstantRange push_range = {VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(float)};
    VkPipelineLayoutCreateInfo layout_info = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
                                              .pushConstantRangeCount = 1,
                                              .pPushConstantRanges = &push_range};
    VkPipelineLayout layout;
    VK_CHECK(vkCreatePipelineLayout(device, &layout_info, NULL, &layout));
    VkPipeline background = vulkan_pipeline(
        device, render_pass, layout, extent,
        vulkan_shader(device, background_vert_spv, sizeof background_vert_spv),
        vulkan_shader(device, background_frag_spv, sizeof background_frag_spv), 0);
    VkPipeline quads = vulkan_pipeline(device, render_pass, layout, extent,
                                       vulkan_shader(device, quad_vert_spv, sizeof quad_vert_spv),
                                       vulkan_shader(device, quad_frag_spv, sizeof quad_frag_spv), 1);

    /* One vertex buffer, rewritten every frame; frames do not overlap. */
    VkBufferCreateInfo buffer_info = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                                      .size = sizeof(struct vertex) * QUAD_VERTICES,
                                      .usage = VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
                                      .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    VkBuffer vertex_buffer;
    VK_CHECK(vkCreateBuffer(device, &buffer_info, NULL, &vertex_buffer));
    VkMemoryRequirements requirements;
    vkGetBufferMemoryRequirements(device, vertex_buffer, &requirements);
    VkPhysicalDeviceMemoryProperties memory_properties;
    vkGetPhysicalDeviceMemoryProperties(v.physical, &memory_properties);
    const VkMemoryPropertyFlags wanted = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    uint32_t memory_type = UINT32_MAX;
    for (uint32_t i = 0; i < memory_properties.memoryTypeCount && memory_type == UINT32_MAX; i++)
        if ((requirements.memoryTypeBits & (1u << i)) &&
            (memory_properties.memoryTypes[i].propertyFlags & wanted) == wanted)
            memory_type = i;
    if (memory_type == UINT32_MAX)
        unavailable("the Vulkan device has no host-visible memory for vertex data");
    VkMemoryAllocateInfo allocate_info = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                                          .allocationSize = requirements.size,
                                          .memoryTypeIndex = memory_type};
    VkDeviceMemory vertex_memory;
    VK_CHECK(vkAllocateMemory(device, &allocate_info, NULL, &vertex_memory));
    VK_CHECK(vkBindBufferMemory(device, vertex_buffer, vertex_memory, 0));
    void *vertex_data;
    VK_CHECK(vkMapMemory(device, vertex_memory, 0, VK_WHOLE_SIZE, 0, &vertex_data));

    VkCommandPoolCreateInfo pool_info = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
                                         .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
                                         .queueFamilyIndex = v.queue_family};
    VkCommandPool pool;
    VK_CHECK(vkCreateCommandPool(device, &pool_info, NULL, &pool));
    VkCommandBufferAllocateInfo command_info = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                                                .commandPool = pool,
                                                .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                                                .commandBufferCount = 1};
    VkCommandBuffer commands;
    VK_CHECK(vkAllocateCommandBuffers(device, &command_info, &commands));
    VkSemaphoreCreateInfo semaphore_info = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
    VkSemaphore acquired, rendered;
    VK_CHECK(vkCreateSemaphore(device, &semaphore_info, NULL, &acquired));
    VK_CHECK(vkCreateSemaphore(device, &semaphore_info, NULL, &rendered));
    VkFenceCreateInfo fence_info = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    VkFence fence;
    VK_CHECK(vkCreateFence(device, &fence_info, NULL, &fence));

    struct block blocks[5];
    marker_blocks(blocks, (int)extent.width, (int)extent.height, MARK_VULKAN);
    VkClearAttachment clears[5];
    VkClearRect clear_rects[5];
    for (int i = 0; i < 5; i++) {
        clears[i] = (VkClearAttachment){.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT,
                                        .colorAttachment = 0,
                                        .clearValue = {.color = {.float32 = {blocks[i].color.r / 255.0f,
                                                                             blocks[i].color.g / 255.0f,
                                                                             blocks[i].color.b / 255.0f, 1.0f}}}};
        clear_rects[i] = (VkClearRect){.rect = {{blocks[i].x, blocks[i].y},
                                                {(uint32_t)blocks[i].width, (uint32_t)blocks[i].height}},
                                       .baseArrayLayer = 0,
                                       .layerCount = 1};
    }

    struct stats stats = {0};
    double previous = 0;
    for (long frame = 0;; frame++) {
        uint32_t image_index = 0;
        VkResult acquire = vkAcquireNextImageKHR(device, swapchain, UINT64_MAX, acquired, VK_NULL_HANDLE,
                                                 &image_index);
        if (acquire != VK_SUCCESS && acquire != VK_SUBOPTIMAL_KHR)
            unavailable("Vulkan: vkAcquireNextImageKHR returned %d", (int)acquire);
        build_quads(vertex_data, frame, (int)extent.width, (int)extent.height);

        VkCommandBufferBeginInfo begin = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
                                          .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
        VK_CHECK(vkBeginCommandBuffer(commands, &begin));
        VkClearValue clear = {.color = {.float32 = {0, 0, 0, 1}}};
        VkRenderPassBeginInfo pass = {.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
                                      .renderPass = render_pass,
                                      .framebuffer = framebuffers[image_index],
                                      .renderArea = {{0, 0}, extent},
                                      .clearValueCount = 1,
                                      .pClearValues = &clear};
        vkCmdBeginRenderPass(commands, &pass, VK_SUBPASS_CONTENTS_INLINE);
        float t = (float)scene_time(frame);
        vkCmdBindPipeline(commands, VK_PIPELINE_BIND_POINT_GRAPHICS, background);
        vkCmdPushConstants(commands, layout, VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof t, &t);
        vkCmdDraw(commands, 3, 1, 0, 0);
        vkCmdBindPipeline(commands, VK_PIPELINE_BIND_POINT_GRAPHICS, quads);
        VkDeviceSize offset = 0;
        vkCmdBindVertexBuffers(commands, 0, 1, &vertex_buffer, &offset);
        vkCmdDraw(commands, QUAD_VERTICES, 1, 0, 0);
        for (int i = 0; i < 5; i++)
            vkCmdClearAttachments(commands, 1, &clears[i], 1, &clear_rects[i]);
        vkCmdEndRenderPass(commands);
        VK_CHECK(vkEndCommandBuffer(commands));

        VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
        VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                               .waitSemaphoreCount = 1,
                               .pWaitSemaphores = &acquired,
                               .pWaitDstStageMask = &wait_stage,
                               .commandBufferCount = 1,
                               .pCommandBuffers = &commands,
                               .signalSemaphoreCount = 1,
                               .pSignalSemaphores = &rendered};
        VK_CHECK(vkQueueSubmit(queue, 1, &submit, fence));
        VK_CHECK(vkWaitForFences(device, 1, &fence, VK_TRUE, UINT64_MAX)); /* the frame is complete before it counts */
        VK_CHECK(vkResetFences(device, 1, &fence));

        track_frame(&w);
        VkPresentInfoKHR present = {.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
                                    .waitSemaphoreCount = 1,
                                    .pWaitSemaphores = &rendered,
                                    .swapchainCount = 1,
                                    .pSwapchains = &swapchain,
                                    .pImageIndices = &image_index};
        VkResult presented = vkQueuePresentKHR(queue, &present);
        if (presented != VK_SUCCESS && presented != VK_SUBOPTIMAL_KHR)
            unavailable("Vulkan: vkQueuePresentKHR returned %d", (int)presented);
        if (frame_done(&w, &stats, &previous))
            break;
    }
    vkDeviceWaitIdle(device);

    char api[96], renderer[VK_MAX_PHYSICAL_DEVICE_NAME_SIZE + 32];
    snprintf(api, sizeof api, "Vulkan %u.%u.%u", VK_VERSION_MAJOR(v.properties.apiVersion),
             VK_VERSION_MINOR(v.properties.apiVersion), VK_VERSION_PATCH(v.properties.apiVersion));
    snprintf(renderer, sizeof renderer, "%s (%s)", v.properties.deviceName,
             vulkan_device_type(v.properties.deviceType));
    report(&w, &stats, renderer, api, v.properties.deviceType != VK_PHYSICAL_DEVICE_TYPE_CPU, present_mode_name,
           MARK_VULKAN);
}

/* --------------------------------------------------------------- info --- */

/* What the display's OpenGL ES and Vulkan implementations are, for the
 * workload script and for diagnosis. Prints one JSON object. */
static void run_info(void)
{
    struct window w;
    open_window(&w);
    printf("{\"width\": %d, \"height\": %d, \"presentation_feedback\": %s", w.width, w.height,
           w.presentation ? "true" : "false");

    EGLDisplay display = eglGetDisplay((EGLNativeDisplayType)w.display);
    static const EGLint config_attributes[] = {EGL_SURFACE_TYPE, EGL_WINDOW_BIT, EGL_RENDERABLE_TYPE,
                                               EGL_OPENGL_ES2_BIT, EGL_NONE};
    static const EGLint context_attributes[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
    EGLConfig config;
    EGLint count = 0;
    EGLContext context = EGL_NO_CONTEXT;
    if (display != EGL_NO_DISPLAY && eglInitialize(display, NULL, NULL) && eglBindAPI(EGL_OPENGL_ES_API) &&
        eglChooseConfig(display, config_attributes, &config, 1, &count) && count == 1)
        context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attributes);
    struct wl_egl_window *native = wl_egl_window_create(w.surface, w.width, w.height);
    EGLSurface surface = context != EGL_NO_CONTEXT
                             ? eglCreateWindowSurface(display, config, (EGLNativeWindowType)native, NULL)
                             : EGL_NO_SURFACE;
    if (surface != EGL_NO_SURFACE && eglMakeCurrent(display, surface, surface, context)) {
        const char *renderer = (const char *)glGetString(GL_RENDERER);
        printf(", \"gles\": {\"renderer\": ");
        json_string(renderer);
        printf(", \"version\": ");
        json_string((const char *)glGetString(GL_VERSION));
        printf(", \"accelerated\": %s}", is_software_renderer(renderer) ? "false" : "true");
    } else {
        printf(", \"gles\": null");
    }

    static const char *extensions[] = {VK_KHR_SURFACE_EXTENSION_NAME, VK_KHR_WAYLAND_SURFACE_EXTENSION_NAME};
    VkApplicationInfo application = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_0};
    VkInstanceCreateInfo instance_info = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
                                          .pApplicationInfo = &application,
                                          .enabledExtensionCount = 2,
                                          .ppEnabledExtensionNames = extensions};
    VkInstance instance;
    printf(", \"vulkan\": [");
    if (vkCreateInstance(&instance_info, NULL, &instance) == VK_SUCCESS) {
        VkPhysicalDevice devices[16];
        uint32_t device_count = 16;
        vkEnumeratePhysicalDevices(instance, &device_count, devices);
        for (uint32_t i = 0; i < device_count; i++) {
            VkPhysicalDeviceProperties properties;
            vkGetPhysicalDeviceProperties(devices[i], &properties);
            printf("%s{\"name\": ", i ? ", " : "");
            json_string(properties.deviceName);
            printf(", \"type\": \"%s\", \"accelerated\": %s}", vulkan_device_type(properties.deviceType),
                   properties.deviceType != VK_PHYSICAL_DEVICE_TYPE_CPU ? "true" : "false");
        }
    }
    printf("]}\n");
    fflush(stdout);
}

int main(int argc, char **argv)
{
    process_start = now();
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (argc < 2) {
        fprintf(stderr, "usage: emugfx wayland|gles|vulkan|info [--seconds S] [--hold S]\n");
        return 64;
    }
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--seconds") && i + 1 < argc)
            opt_seconds = atof(argv[++i]);
        else if (!strcmp(argv[i], "--hold") && i + 1 < argc)
            opt_hold = atof(argv[++i]);
        else {
            fprintf(stderr, "emugfx: unknown option %s\n", argv[i]);
            return 64;
        }
    }
    if (opt_seconds <= 0)
        opt_seconds = 5.0;
    test_name = argv[1];
    if (!strcmp(test_name, "wayland"))
        run_wayland();
    else if (!strcmp(test_name, "gles"))
        run_gles();
    else if (!strcmp(test_name, "vulkan"))
        run_vulkan();
    else if (!strcmp(test_name, "info"))
        run_info();
    else {
        fprintf(stderr, "emugfx: unknown test %s\n", test_name);
        return 64;
    }
    return 0;
}
