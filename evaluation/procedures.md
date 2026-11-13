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
checks play them into a private output device of the host's sound server,
record that device, and look for the pitches; for mute they look for the
silent stretch in the middle of a tone. Nothing is heard while they run.

## Web

Defined for stage 5. WPE WebKit plays a reference stream through MSE and
renders a fixed animated page.
