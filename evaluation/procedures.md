# Measurement procedures

How performance results are produced, so that a result from one host can be
compared with a result from another. The workloads are defined in
[workloads.json](workloads.json) and the combinations to cover in
[matrix.json](matrix.json).

## Rules for every measurement

1. **One combination at a time.** A run measures one host, one host CPU
   architecture and one emulator mode (`container`, `vm-native`, `vm-arm32`,
   `vm-arm64`).
2. **Fixed emulator size.** 4 CPUs and 2048 MiB of memory (the launcher's
   defaults) unless the result is explicitly about another size. In container
   mode the container engine must have at least that much; the engine's own
   CPU count and memory are recorded with the result.
3. **Quiet host.** Mains power, no other emulator or build running, and
   nothing else competing for the CPU or disk.
4. **Current image.** The launcher rebuilds the client OS image when its
   definition has changed. Never measure with a hand-modified image.
5. **Three runs, report the median.** Start the emulator fresh for each run
   (`--repeat 3`). Each run is recorded separately; the comparison uses the
   median of each test and shows the spread.
6. **Record, do not transcribe.** Results are written by the launcher
   (`--record`) to `evaluation/results/`. Numbers are never typed in by hand.
7. **Unavailable is a result.** When a combination or test cannot be run,
   that is stated with the reason. A test that fails inside the target
   reports `"value": null` and an `"unavailable"` reason. Nothing is
   estimated or carried over from another combination.
8. **Same workload version.** Only results from the same workload version
   are compared. A workload's version changes when its method changes.

## What identifies a result

Every record in `evaluation/results/` carries:

| Field | Identifies |
|---|---|
| `host` | host OS and version, CPU architecture, CPU model, CPU count, memory, GPUs with their drivers (`gpus`; absent in records made before it was added) |
| `emulator` | mode and variant, guest architecture, accelerator, CPU model, runtime and its version, CPUs, memory, options; for runs with a display, its resolution and whether graphics were emulated or mapped to the host, with the reason |
| `image` | client OS image name and version, its source (Debian release, base image digest, apt snapshot), the SHA-256 of its build definition, the repository revision it was built from, and the SHA-256 of the root filesystem or the container image ID; plus what the running target reported about itself |
| `workload` | workload id, version and arguments |
| `boot_seconds` | time from starting the emulator until the target OS reported ready |

`./emu verify results` fails if any record lacks one of these.

## Resource benchmarks

Workload `bench` (CPU, memory allocation, memory bandwidth, I/O).

    ./emu run --mode container --workload bench --record --repeat 3
    ./emu run --mode vm --arch native --workload bench --record --repeat 3
    ./emu run --mode vm --arch arm64 --workload bench --record --repeat 3
    ./emu run --mode vm --arch arm32 --workload bench --record --repeat 3

- Every test runs for a fixed wall-clock time (2 seconds by default,
  `--seconds`), so the suite takes about as long under CPU emulation as it
  does natively.
- I/O tests run on `/data`, the target's writable data partition. In VM mode
  that is an ext4 filesystem on a virtio disk backed by a raw file on the
  host, formatted at boot. In container mode it is a volume of the container
  engine. The I/O results therefore describe the emulator's storage path, not
  the host disk alone.
- Reads use `O_DIRECT` so the target's page cache is not what is measured;
  each I/O result says whether direct I/O was in effect.

## Functional checks

Workload `prompt` starts an interactive shell on the target OS. The automated
check types a command into it and expects the computed answer back
(`./emu verify prompt-container prompt-vm`).

## Driver strategies

Workload `driver-check` reads a driver feature through its target OS
interface and reports what it observed (`./emu verify drivers-container
drivers-vm`). For `hwrng` the check proves which strategy served the read:

- `mocked`: the 16-byte sample equals the stub's fixed pattern.
- `host`: the sample appears in the byte stream the host-side process logged.
- `emulated`: no host-side process ran, and the target names the emulated
  provider (the kernel's virtio-rng driver in VM mode, the software device
  model in container mode).

## Graphics

Workload `graphics-demo`. One run measures one display resolution; run each
combination at all three.

    ./emu run --mode container --workload graphics-demo --resolution 720p --record --repeat 3
    ./emu run --mode container --workload graphics-demo --resolution 1080p --record --repeat 3
    ./emu run --mode container --workload graphics-demo --resolution 4k --record --repeat 3

and the same for `--mode vm --arch native`, `--arch arm64` and `--arch arm32`.

- Four tests, one per graphics technology: `wayland_fps` (a Wayland client
  drawing with the CPU into shared memory), `gles_fps` (OpenGL ES 2.0),
  `vulkan_fps` and `flutter_fps`. Each shows a fixed animated scene full
  screen for a fixed time (5 seconds by default, `--seconds`; `--tests`
  selects tests).
- The animation advances by frame number, so every run draws the same frames
  in the same order however fast it goes.
- The Wayland, OpenGL ES and Vulkan tests finish each frame and submit it
  without waiting for the display. Their `value` is frames rendered per
  second; `displayed_fps` is how many of those the compositor reported as
  shown. The Flutter test follows the display instead, as Flutter applications
  do: it draws at most one frame each time the compositor shows one, and
  reports how long building and rasterising each frame took.
- The display paces differently in the two modes, which bounds
  `displayed_fps` and the Flutter frame rate. Container mode has no display
  device; its headless compositor output simulates a 60 Hz display. VM mode's
  emulated display device has no refresh signal, so the compositor updates it
  as often as it can compose a frame.
- Each result names what rendered it (`renderer`) and whether that was host
  graphics acceleration (`accelerated`); the record's `emulator.graphics` says
  which provider the launcher selected and why. With `--graphics auto` (the
  default) the launcher uses host acceleration when the host has a compatible
  one and falls back to emulation otherwise. A comparison must only put
  results with the same provider side by side.
- A technology that the target image cannot run on an architecture reports
  `"value": null` with the reason.

`./emu verify` checks the display itself, not only what the target reports:
at the end of each test the launcher captures the emulator's display (through
QEMU in VM mode, from the compositor in container mode) and checks its size
and the marker blocks that test draws. `--screenshot DIR` saves the same
captures as PNG files.

## Audio and video decoding

Workload `media-decode`.

    ./emu run --mode container --workload media-decode --record --repeat 3
    ./emu run --mode vm --arch native --workload media-decode --record --repeat 3
    ./emu run --mode vm --arch arm64 --workload media-decode --record --repeat 3
    ./emu run --mode vm --arch arm32 --workload media-decode --record --repeat 3

- **Reference streams.** Built with the image by
  [target/media/build-media.sh](../target/media/build-media.sh): 1280x720
  video at 25 frames/s, 5 seconds, a moving test pattern; and 30-second
  audio-only streams. Each video codec (MPEG-2, AVC, HEVC) is encoded once and
  packed unchanged into each container (MP2TS, MP4, fragmented MP4 split into
  an initialisation segment and one fragment per group of pictures). The
  streams are the same on every target architecture. A result names its
  stream and the SHA-256 of the stream's bytes; the streams are part of the
  workload's version.
- **Decode speed** (`video_decode_speed`, `audio_decode_speed`, one case per
  stream). The `ffmpeg` program decodes the stream as fast as it can, on all
  of the target's CPUs, and discards the output. The value is media seconds
  decoded per second of the decoder's own running time (`x realtime`). A
  stream that decodes in well under a second is decoded again until a second
  has been timed. For the fragment cases the fragments are appended to the
  decoder's input one after another while it runs.
- **Dropped frames** (`playback_dropped_frames`, one case per stream and
  graphics technology). The stream is played once in real time, full screen,
  with its sound on the target's audio device. By default one stream per
  video codec is played, each arriving a different way (MPEG-2 in MP2TS, AVC
  in MP4, HEVC as fragments); `-- --full` plays all nine. The value is the
  number of the stream's 125 frames that were not shown:
  - Wayland, OpenGL ES and Vulkan: the mpv player's own count of frames it
    dropped, in its output and in its decoder.
  - Flutter: the `ffmpeg` program decodes in real time and hands the frames to
    the Flutter application, which always draws the newest one; frames that
    were replaced before the application could draw them are the dropped ones.
  The two counts come from different players and are not comparable with each
  other; compare a technology with itself across hosts and modes.

  Both are the players' own counts, not the display's. They were compared
  with the display's own record (the compositor's count of repaints with new
  content, see [MSE playback](#web)) on the macOS host on 2026-11-15, at 1080p
  with emulated graphics, each stream played at least once in every mode:
  - Container, host-native VM and ARM64 VM modes, every technology, and
    Wayland in ARM32 VM mode: the display showed at most three fewer new
    frames than the player counted as shown. (For Flutter it showed a few
    more: the application draws its window before the stream starts.)
  - OpenGL ES in ARM32 VM mode: mpv counted 19 to 45 of a stream's frames as
    shown, and the display showed 13 to 34, six to eleven fewer each time.
    The value understates the loss by that much. The likely cause, not
    checked: mpv is told to draw without waiting for the display
    (`--force-render`), and where the display is slower still, a frame is
    replaced by the next before it was shown.

  The value is unchanged by this: it is still the player's count. Not
  compared on the other hosts.
- Fragments are appended ahead of playback: a fragment when less than two
  seconds of media are buffered ahead of the playback position.
- The record's `emulator.graphics` and `emulator.audio` say how graphics and
  sound were provided. Results of playback with different graphics providers
  must not be put side by side.
- A sound that plays on the host is part of the run; for a measured run on a
  shared machine use `--mute` or `--option audio-output=none`.

`./emu verify` checks what the target reports against the outside: a capture
of the emulator's display during each playback must show the stream's marker
blocks (the four corners, and one whose colour names the video codec), and
the sound must arrive on the host. Each audio stream is a tone whose pitch
names its codec (MP2 440 Hz, AC-3 660 Hz, AAC 880 Hz, HE-AAC 1100 Hz). The
checks look for the pitches in a recording made on the host; for mute they
look for the silent stretch in the middle of a tone. Nothing is heard while
they run. Where the recording is made depends on the host:

- Linux: the tones are played into a private output device of the host's
  sound server (PulseAudio or PipeWire), and that device is recorded.
- macOS: there is no private output device without installing an audio
  driver. The tones are played on the default output device at volume 0. The
  launcher's player records what the system's audio queue takes for the
  device, which the queue does at the device's own pace, and reports how long
  the device played by its own clock. The check also asks the system's audio
  server whether it sees the player process playing, and on which device.
  This shows that the host's audio output took the sound; it is not a
  recording of what left the device.
- Windows: the same as on macOS, with the launcher's player for Windows. The
  tones are played on the default output device with the player's volume in
  the Windows mixer at 0 (the player puts the volume back afterwards). The
  player records what the wave output takes for the device, at the device's
  pace, and reports the device's own count of the samples it played. The
  check also asks the Windows audio service whether it has a session of the
  player process that is playing, and on which device.

## Remote control input

Functional checks of the launcher's windows and of remote control input
(tasks 7.1 to 7.5); nothing here is a measurement. The `remote-keys` workload
is their target side: it puts one full-screen window on the target's display,
a still picture with the marker blocks of the graphics workloads, and prints
a line for every key that window gets, with the key's Linux code and the
symbol the target's keymap gives it.

    ./emu run --mode container --workload remote-keys --remote-control window
    ./emu verify window-display-vm window-scaling-vm window-toolbar-vm window-fullscreen-vm
    ./emu verify remote-keys-vm remote-window-vm settings-window settings-launch

`./emu verify` runs the workload once per mode with the display window and
the on-screen remote control, and drives the window as a person would,
through the window's own command channel (`--control`): keys typed into it
and mouse clicks on its buttons go through Qt's event handling like real
ones. What each check goes by:

- **The display in the window** (`window-display-*`). The window saves the
  display as it arrived; the marker blocks must be where the target drew
  them. This is the picture the window holds, not a photograph of the screen:
  what is on the physical screen is not captured.
- **Scaling** (`window-scaling-*`). The window is given two sizes, one of the
  display's shape and one of another; each time it saves the part that shows
  the display, which must have the expected size and all the marker blocks.
- **Toolbar** (`window-toolbar-*`). After the 1:1 button the display must be
  drawn on as many screen pixels as it has. The mute button is pressed twice;
  each time the run's audio process is asked whether it is muted.
- **Full screen** (`window-fullscreen-*`). Ctrl+Alt+F and then F11 are typed
  into the window. It must report full screen without its toolbar, cover the
  screen and show the whole picture scaled to it, and come back as it was. A
  window that reports full screen without growing makes the check
  "unavailable", with the reason: the window system did not carry it out.
- **Host keys** (`remote-keys-*`) and **the on-screen remote control**
  (`remote-window-*`). For each of the 32 keys, its host key is typed into
  the display window, and its button is clicked; each time the target must
  print that key's code, pressed and released, and nothing else.
- **Settings window** (`settings-window`, `settings-launch`). Fields are set
  and Start is clicked; the arguments must be what the launcher's parser reads
  as those settings, and there must be a field for every argument of
  `emu run`. Then the launcher is started without arguments, a workload is
  chosen in the window, and its results must be those of the same arguments
  on the command line.

Not checked: that keys stay away from the target while another window has the
focus, and anything about RedRat IR input, which is not implemented.

## Web

Workload `web-bench`. The browser is WPE WebKit, started by its launcher Cog
as a Wayland client, full screen on the target's display.

    ./emu run --mode container --workload web-bench --record --repeat 3
    ./emu run --mode vm --arch native --workload web-bench --record --repeat 3
    ./emu run --mode vm --arch arm64 --workload web-bench --record --repeat 3
    ./emu run --mode vm --arch arm32 --workload web-bench --record --repeat 3

- **Pages.** The workload's own, in
  [target/rootfs/opt/emu/web](../target/rootfs/opt/emu/web). The workload
  serves them to the browser over the target's loopback interface, and a page
  reports what it measured back to the workload. The browser is started anew
  for each test and each stream, and so is the target's display service: on
  the simulated ARM32 target the compositor does not survive a second browser
  while its record is being read (see MSE playback).
- **Launch** (`web_launch`, a functional test). The browser starts, loads a
  page and runs its script; the page reports the browser's user agent, the
  size of its viewport and whether it has Media Source Extensions. The value
  is the time from starting the browser to the page's report.
- **Rendering** (`web_render_fps`). A fixed animated page
  ([render.html](../target/rootfs/opt/emu/web/render.html)): a rotating
  background, 64 blended shapes and a grid of 24 text elements, all of them
  page elements, moved once per animation frame for 5 seconds
  (`-- --seconds S`) at the display resolution (`--resolution`). The browser
  draws one frame per display refresh, so the frame rate is bounded by the
  60 Hz display, as the Flutter test's is. Reported with percentiles of the
  time between frames, and with `displayed_fps`: how often the display showed
  something new in that time, by the compositor's own record (see MSE
  playback). The value is the page's count of the frames it drew.
- **MSE playback** (`mse_playback_dropped_frames`). The fragmented streams of
  the media-decode workload, one per video codec (MPEG-2 with MP2, AVC with
  AAC, HEVC with AC-3; `-- --streams` selects). A page
  ([mse.html](../target/rootfs/opt/emu/web/mse.html)) appends a stream's
  initialisation segment and its media fragments to a Media Source buffer,
  keeping two seconds ahead of the playback position, and the browser plays
  them in real time, full screen, with their sound on the target's audio
  device. The value is the stream's frames that did not reach the display:
  all 125, less the frames shown. The frames shown are the smaller of two
  counts (`displayed_frames`):
  - the browser's (`shown_frames`): the frames it counted at its video output
    and did not drop there (`getVideoPlaybackQuality()`). The browser's own
    count of dropped frames is not the value, because it covers only frames
    that got as far as the output: under CPU emulation the decoder can skip
    most of a stream before that.
  - the display's (`display_repaints`): how often the display showed
    something new while the stream played. The target's compositor records
    every repaint and whether it had new content of a client (Weston's
    timeline, read with `weston-debug`); the workload counts those from 0.1 s
    before the browser reported the stream playing to 0.25 s after its end.
    A frame at the browser's output is not yet on the display: the browser
    still has to draw the page with it, and where that drawing is slower than
    the stream the display shows a few frames of a stream whose every frame
    the browser counted. (On a simulated ARM target on the macOS host: 125
    counted by the browser, 5 to 9 shown.)

  The result has both counts, the browser's count of dropped frames, the
  times playback stalled, and whether the sound was on. A stream the browser
  does not play is reported with `"value": null` and the browser's reason,
  and so is one whose display record cannot be read. Before version 1.1.0 of
  the workload the value was the browser's count alone; those results are not
  comparable and the results page does not chart them.
- **What is changed about the browser.** Two things, both because the target
  runs it unattended: WebKit's process sandbox is off (it needs kernel
  features a container does not give, and the browser loads nothing but the
  workload's pages), and those pages may start media with sound, which WebKit
  otherwise allows only after a click
  ([target/src/emu_web_autoplay.c](../target/src/emu_web_autoplay.c)).
- **Graphics provider.** As for the graphics workload: results with emulated
  and with host graphics are kept apart.

`./emu verify` captures the display for each test, as for the graphics and
media workloads: the pages draw the same marker blocks, and a played stream
is paused on a frame for the capture (not in a measured run).
