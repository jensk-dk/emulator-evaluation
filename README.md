# emulator-evaluation

<picture>
  <img alt="Emu Device Emulator" src="docs/emu-logo.svg" width="150" height="150">
</picture>

This repo contains a generic device emulator for Linux-based TVs and set-top boxes. Features:

* Runs on Linux, Mac and Windows hosts.
* Setup script that can check or install required dependencies for each host OS.
* VM mode for development and Container mode for CI.
* Supports Wayland, OpenGL ES, Vulkan and Flutter graphics on target OS.
* Supports A/V decoding in emulator with common broadcast and broadband A/V formats and codecs
* Unified command line command regardless of the underlying emulator technology used.
* Comprehensive performance analysis and reporting

The requirements live in the [openspec](openspec) folder. Delivery is staged
([tasks](openspec/changes/staged-emulator-delivery/tasks.md)); this repo
holds the code for stages 0 to 4: the evaluation foundation, a cross-platform
runnable baseline, VM CPU and driver fidelity, graphics, and media playback.
Stages 0 to 3 are verified on three hosts: macOS on ARM64, Windows on x86-64
with Podman as the container runtime, and Linux on x86-64 (Kubuntu 24.04)
with Docker. Stage 4 is verified on the Linux and macOS hosts; on Windows its
decoding and video parts are expected to work as they are, and playing the
target's sound through the host is still to be done there. macOS has no host
graphics acceleration, which the Linux host has in VM mode. The task list and
`evaluation/verification/` show what has been verified, and on which hosts.

## Quick start

    ./setup.sh              # Linux and macOS: check and install host dependencies
    ./emu run               # interactive prompt on the target OS, container mode
    ./emu run --mode vm     # the same in a host-native VM
    ./emu run --mode vm --workload graphics-demo --screenshot shots   # graphics, with display captures
    ./emu run --mode vm --workload graphics-demo --window             # graphics, with the display in a window
    ./emu run --mode vm --workload media-decode --window              # decoding and playing video and sound
    ./emu audio mute                                                  # from another terminal, while it plays

On Windows use `setup.cmd` and `emu.cmd`. (`setup.cmd` runs `setup.ps1`
where the PowerShell execution policy does not allow scripts, which is the
default.)

The first run builds the target OS image, which downloads Debian packages and
takes a few minutes. Later runs start in seconds.

## Host setup

`setup.sh` (Linux, macOS) and `setup.ps1` (Windows) check for every host
dependency and install what is missing. `--check` / `-Check` only reports.

| Dependency | Used for | macOS | Linux | Windows |
|---|---|---|---|---|
| Python 3.9+ | the launcher | Xcode Command Line Tools | system package | winget |
| QEMU system emulators | VM mode | Homebrew `qemu` | system package | winget |
| Hardware virtualization | host-native VM mode | Hypervisor.framework | KVM | Windows Hypervisor Platform |
| Container runtime | container mode, image builds | Colima + Docker CLI (Homebrew) | Podman | Podman |
| Foreign-architecture emulation | building ARM target images | registered in the engine VM | `qemu-user-static` | registered in the engine VM |
| Audio player (optional) | playing the target's sound on the host | built by the launcher with the Command Line Tools' compiler | `pacat`, `pw-cat` or `aplay`; system package | not implemented yet |
| QEMU OpenGL modules (optional) | mapping VM graphics to the host GPU | not in Homebrew's QEMU; an experimental build has them, installed only with `./setup.sh --experimental-qemu` (see [Experimental: host graphics on macOS](#experimental-host-graphics-on-macos)) | system package | in winget's QEMU; used when the display is in a window (see [Display and graphics](#display-and-graphics)) |

An existing Docker or Podman installation is used as it is. Where both are
installed, Docker is used when its engine answers. To choose, set the
environment variable `EMU_CONTAINER_RUNTIME` to `podman` or `docker`; the
launcher and `setup.ps1` read it.

The launcher starts a stopped container engine itself. On macOS, restarting
Colima drops the ARM32 build emulation; `./setup.sh` restores it, and it is
only needed to rebuild the ARM32 image.

### Linux

`setup.sh` installs with the distribution's package manager (apt, dnf, pacman
or zypper) and asks for root through `sudo`. It has been run on Kubuntu 24.04
only.

- An installed Docker is used as it is, also an old one: the launcher builds
  with BuildKit, which Docker engines before version 23 do not do by default
  and which building the ARM images needs. Run with Docker 20.10.
- Host graphics acceleration needs a loaded GPU driver, which shows as a
  render node (`/dev/dri/renderD*`). Without one the host renders its own
  graphics on the CPU, and the launcher emulates graphics rather than hand
  them to that. `setup.sh` reports this and does not install GPU drivers.
  (After a kernel update, check that the driver's kernel module was updated
  with it: `./emu doctor` shows whether host acceleration is available.)

### Windows

Nothing on Windows needs Docker Desktop or a sign-in: `setup.cmd` installs
QEMU and Podman with winget (each installer asks for elevation once) and
creates Podman's engine, which runs in WSL 2.

- The Podman machine is created rootful. A rootless one cannot register the
  ARM build emulation, and cannot give a container CPUs of its own: the
  launcher then limits CPU time instead and says so.
- Host-native VM mode uses the Windows Hypervisor Platform. Where WSL 2 works
  it is usually available already; otherwise `setup.ps1` says which Windows
  feature to enable.
- Building the images writes many gigabytes into Podman's virtual disk
  (`ext4.vhdx`), and that file does not shrink when the data is deleted. Here
  it was 13 GB after the x86-64 images and 18 GB once the ARM64 image was
  built too, and Windows grew its page file by several gigabytes during the
  builds. To get the space back afterwards, save the container image
  (`podman save`), remove and recreate the machine (`podman machine rm`,
  `setup.cmd`), and load it again. VM mode needs nothing from the engine once
  its image is built.

## Launcher

    ./emu run [--mode container|vm] [--arch native|arm32|arm64] [--workload NAME]
              [--cpus N] [--memory MIB] [--resolution 720p|1080p|4k] [--graphics auto|host|emulated]
              [--window] [--driver FEATURE=STRATEGY] [--option KEY=VALUE] [--screenshot DIR]
              [--mute] [--record] [--repeat N] [-- WORKLOAD_ARGS]

| Mode | What runs |
|---|---|
| `--mode container` | the target OS userland on the container runtime, for quick development and CI |
| `--mode vm` | the target OS kernel and userland in a QEMU virtual machine |
| `--mode vm --arch native` | the host's own CPU architecture on the host's hypervisor |
| `--mode vm --arch arm64` | a simulated 64-bit ARM target CPU (Cortex-A53) |
| `--mode vm --arch arm32` | a simulated 32-bit ARM target CPU (Cortex-A15) |

`--arch x86_64` also exists, to try the x86-64 image under emulation on an
ARM host. It is a diagnostic and not part of the test matrix.

Workloads: `prompt` (interactive shell), `bench` (CPU, memory and I/O
benchmarks), `driver-check`, `graphics-demo` and `media-decode`.
`./emu workloads` lists them, including the web workload that is defined for
a later stage.

Other commands: `./emu build`, `./emu doctor`, `./emu matrix`,
`./emu workloads`, `./emu verify`, `./emu report`, `./emu audio`. Each has
`--help`.

## Target OS image

[target/Dockerfile](target/Dockerfile) defines the simulated target OS once,
on Debian 13. The container runtime builds it either as a container image or
as VM artifacts (ext4 root filesystem, Debian kernel, initramfs), for x86-64,
ARM64 and ARM32. [target/image.json](target/image.json) pins its source: the
base image digest and a dated Debian package snapshot.

[target/rootfs/opt/emu/init](target/rootfs/opt/emu/init) is the target's init
in both modes: PID 1 in a VM, the entrypoint in a container. It brings up the
environment, starts the driver-feature providers and runs one workload.

For graphics the image carries the Weston Wayland compositor, Mesa's OpenGL ES
and Vulkan drivers, and a Flutter application built with a pinned Flutter SDK.
For media it carries FFmpeg's decoders with the `ffmpeg` program, the mpv
player and ALSA as the audio interface. These are choices for the evaluation
image, not statements about the real target's middleware.

Two graphics technologies do not run in ARM32 mode yet. The Flutter SDK builds
Linux applications for x86-64 and ARM64 only, so the ARM32 image has no
Flutter workload. And Mesa's CPU-rendered Vulkan driver crashes on 32-bit ARM
(in the image's Mesa 25.0 even with Debian's own `vkcube` demo), so Vulkan
with emulated graphics is unavailable there. Wayland and OpenGL ES work in
ARM32 mode.

## Driver features

A driver feature can be provided three ways, in both modes
(`--driver FEATURE=emulated|mocked|host`):

| Strategy | VM mode | Container mode |
|---|---|---|
| `emulated` | QEMU emulates the device; the target kernel's own driver runs it | a software model of the device behind the driver's interface |
| `mocked` | a stub behind the driver's interface returns canned data | the same stub |
| `host` | the emulated device's backend is a host-side process that uses the host OS | a shim forwards the driver's interface to the host-side process |

There are two features. `hwrng` is the hardware random number generator at
`/dev/hwrng`; every run has it, emulated unless told otherwise. `audio` is
sound output on the ALSA device `default`; a run has it when its workload
plays sound or when `--driver audio=...` asks for it, and its default
strategy is `host` (see [Media playback](#media-playback)). The host halves
are in [emulator/drivers.py](emulator/drivers.py),
[emulator/hostd.py](emulator/hostd.py) and
[emulator/hostaudio.py](emulator/hostaudio.py); the target halves in
[target/rootfs/opt/emu/drivers](target/rootfs/opt/emu/drivers).

In container mode the shim reaches the host-side process over the network.
Podman's engine on Windows has no route to a process on Windows' loopback
address, so there a relay container on the engine's network carries the
connections to the host over its standard streams
([emulator/relay.py](emulator/relay.py)). No firewall rule or WSL setting is
involved.

## Display and graphics

The emulator has a display when the workload uses one, or when `--resolution`,
`--graphics` or `--window` is given. `--resolution` selects 720p, 1080p (the
default) or 4K.

| | VM mode | Container mode |
|---|---|---|
| Display | QEMU's emulated display adapter, driven by the target kernel's DRM/KMS driver | none; the compositor renders to a headless output of the selected size |
| `--window` | the display is shown in a window of its size | not available |
| `--graphics emulated` | the target CPU renders OpenGL ES and Vulkan (Mesa llvmpipe and lavapipe) | the same |
| `--graphics host` | QEMU's virtio-gpu maps OpenGL ES, and Vulkan where QEMU offers it, to the host GPU | the container gets the engine's GPU render node (`/dev/dri`) |

`--graphics auto`, the default, uses host acceleration when the host has a
compatible one and otherwise emulates; the launcher prints which it chose and
why. `--graphics host` fails rather than silently emulating.

Without `--window` a VM's display is not shown anywhere; `--screenshot`
captures it. `--window` shows it in QEMU's SDL window, or in QEMU's Cocoa or
GTK window where the build has no SDL. Closing the window ends the emulator.
The SDL window has been run on Windows and on Linux (X11), the Cocoa window
on macOS. The windowed display of the later stage (full screen, scaling,
toolbar) is not part of this.

What the verified hosts offer; `./emu doctor` shows it for any host:

- macOS on ARM64, with the QEMU that `setup.sh` installs: no host
  acceleration, in either mode. Homebrew's QEMU is built without the
  GPU-accelerated display device, and QEMU itself has no OpenGL display for
  macOS. The container engine's virtual machine has no GPU. `--window` shows
  the emulated display in QEMU's Cocoa window, and such a display can be
  captured.
- macOS on ARM64, with an experimental QEMU build: host acceleration in VM
  mode with `--window`. See
  [Experimental: host graphics on macOS](#experimental-host-graphics-on-macos).
- Linux on x86-64 (Kubuntu 24.04, QEMU 8.2.2, NVIDIA GPU with NVIDIA's own
  driver), VM mode: host acceleration, with and without a window. QEMU maps
  OpenGL ES to the host GPU; `./emu verify` covers this path here, by a capture
  of the display. Without a window at 1080p the OpenGL ES test ran at 183
  frames/s and the Flutter test at 60, against 51 and 9 emulated. Simulated ARM
  targets get it as well: OpenGL ES at 118 frames/s on ARM64 and 84 on ARM32,
  against about 1 emulated. Vulkan stays on the
  target CPU: this QEMU does not map it. QEMU ends cleanly. Two limits:
  - Without a window, a capture of a 4K display shows only its top left
    2560x2048 pixels: QEMU's VNC server shows no more. The target renders all
    of it; the launcher says so when it saves such a capture.
  - With a window the display cannot be captured, as on Windows.
- Linux on x86-64, container mode: emulated. The engine has the GPU's render
  node, but it belongs to NVIDIA's driver, which the target's graphics stack
  (Mesa) cannot render with. A GPU with a Mesa driver (Intel, AMD) is still to
  be run.
- Windows on x86-64, VM mode with `--window`: host acceleration. QEMU 11.1.0
  maps OpenGL ES to the host GPU and shows it in its window. On an NVIDIA GPU
  the OpenGL ES test ran at 175 frames/s and the Flutter test at 59, against
  99 and 17 emulated in the same window. A simulated ARM64 target gets it as
  well: OpenGL ES at 75 frames/s, against 2 emulated. Vulkan stays on the
  target CPU. Two limits:
  - QEMU ends with an access violation once the target has shut down. The
    workload's results are complete by then; the launcher reports the status.
  - Such a display cannot be captured, so `--screenshot` says so instead of
    saving a picture, and `./emu verify` does not cover this path.
- Windows on x86-64, VM mode without a window: emulated. The display QEMU
  offers for host rendering without a window (`egl-headless`) stays black, so
  the launcher does not use it there.
- Windows on x86-64, container mode: emulated. Podman's engine in WSL has no
  GPU render node.

The launcher captures a VM's display through QEMU's machine protocol. QEMU
refuses that while the display is a texture on the host GPU. Without a window
the capture is then read from QEMU's VNC server. That works on Linux, up to
2560x2048 pixels; on Windows it returns the black display described above.

### Experimental: host graphics on macOS

A patched QEMU from a third-party Homebrew tap
([milesbuckton/homebrew-qemu-virgl](https://github.com/milesbuckton/homebrew-qemu-virgl))
adds an OpenGL mode to QEMU's Cocoa window, through ANGLE. It is not a
dependency of this project: it is one person's fork of QEMU's unreleased
development branch. `setup.sh` installs it only when asked to:

    ./setup.sh --experimental-qemu

The option needs the Xcode app, which ANGLE's build uses; the Command Line
Tools are not enough. Xcode does not have to be the selected developer
directory. The option then:

1. tells Homebrew to trust the tap, and taps it;
2. takes the tap at the commit below and applies
   [docs/macos-experimental-qemu.patch](docs/macos-experimental-qemu.patch) to
   its formulas. The patch pins the commit each formula builds from, and lets
   ANGLE's build find Xcode where `xcode-select` points at the Command Line
   Tools;
3. builds the formulas from source, in dependency order (`gn`, `libangle`,
   `libepoxy-angle`, `virglrenderer`, `qemu-virgl`);
4. pins the five packages, so that `brew upgrade` does not build them again
   from other commits.

`./setup.sh --check` reports the build wherever it is installed. The commits
it is built from:

| Part | Source | Commit |
|---|---|---|
| Tap | github.com/milesbuckton/homebrew-qemu-virgl | `56626e28` |
| QEMU 11.1.90 | gitlab.com/milesbuckton/qemu | `c95b8c49` |
| virglrenderer | gitlab.freedesktop.org/miles.buckton/virglrenderer | `890d0648` |
| ANGLE | chromium.googlesource.com/angle/angle | `47d8f0e2` |
| libepoxy | github.com/anholt/libepoxy | `d1f952c4` |

Two things can stop the option:

- The tap's history is a single commit. If the tap is rewritten, that commit
  may no longer be there to fetch; the option then stops and says so.
- Homebrew's own `virglrenderer` has the same name as the tap's. Where that
  one is installed, the option stops and does not replace it.

To remove the build again (Homebrew does not uninstall a pinned package):

    brew unpin qemu-virgl virglrenderer libepoxy-angle libangle gn
    brew uninstall qemu-virgl virglrenderer libepoxy-angle libangle gn
    brew untap milesbuckton/qemu-virgl
    brew untrust --tap milesbuckton/qemu-virgl

The build installs beside Homebrew's QEMU. The launcher uses it when the
environment variable `EMU_QEMU_DIR` names its directory; that variable works
for any other QEMU build too. A build that has only the ARM64 emulator, as
this one, then runs ARM32 targets as well.

    EMU_QEMU_DIR=/opt/homebrew/opt/qemu-virgl/bin ./emu run --mode vm --workload graphics-demo --window

What was seen, in single runs that were not recorded as results:

- With `--window`, OpenGL ES and Flutter render on the Apple GPU (the target
  reports `virgl (ANGLE (Apple, Apple M6, OpenGL 4.1 Metal))`), for
  host-native, simulated ARM64 and simulated ARM32 targets. QEMU ends cleanly.
  Vulkan stays on the target CPU.
- Frames per second at 1080p, host graphics against emulated:

  | Test | Host-native | ARM64 | ARM32 |
  |---|---|---|---|
  | OpenGL ES | 100 against 143 | 205 against 2.8 | 104 against 1.5 |
  | Flutter | 60 against 17 | 32 against 0.5 | no Flutter |

  On a host-native target the OpenGL ES test stays at about 100 frames/s at
  every resolution; at 4K that is against 35 emulated, and Flutter stays at 60
  against 5.
- Video playback through OpenGL ES on simulated targets: an ARM64 target
  dropped 0 of 125 frames of the MPEG-2 stream and 19 of the AVC stream
  (against 106 and 108 emulated); an ARM32 target 1 and 0 (against 105 and
  91).
- One playback did not end: the HEVC stream through OpenGL ES on an ARM64
  target ran into the workload's time limit.
- On a host-native target the HEVC stream lost frames with this build (21 of
  125 through Wayland, 26 through OpenGL ES, 61 through Vulkan), where the
  installed QEMU loses none. Not investigated.
- Without a window the build crashes as soon as the target starts to use the
  GPU, so the launcher emulates graphics there and says why.
- The display cannot be captured while it is rendered on the host GPU: QEMU
  refuses the capture over its machine protocol and refuses to start its VNC
  server beside the OpenGL window. `./emu verify` therefore cannot cover this
  path on macOS; `graphics-host-vm` stays unavailable there.

`graphics-demo` runs a Wayland, an OpenGL ES, a Vulkan and a Flutter test.
`--screenshot DIR` saves a PNG of the emulator's display at the end of each
test. On the target, [`/opt/emu/display`](target/rootfs/opt/emu/display)
(`emu-display start`) starts the compositor, for running other Wayland
programs from the prompt.

## Media playback

The `media-decode` workload decodes and plays reference streams that are
built into the image ([target/media](target/media)): 1280x720 video at 25
frames/s with a test tone.

| | Supported |
|---|---|
| Containers | MPEG-2 Transport Stream, MP4, and MSE-style injection: an initialisation segment and media fragments appended one after another to the decoder's input while it runs |
| Video codecs | MPEG-2, AVC, HEVC |
| Audio codecs | MP2, AC-3, AAC, HE-AAC |
| Video output | through Wayland, OpenGL ES and Vulkan with the mpv player, and through the Flutter application, which draws the decoded frames itself |
| Audio output | the target's ALSA device `default`, played through the host OS, with a mute switch |

    ./emu run --mode vm --workload media-decode                  # decode speed, then playback through each technology
    ./emu run --workload media-decode -- --tests playback --technologies gles --streams hevc-fragments
    ./emu run --mode vm --workload prompt --driver audio=host    # a prompt with sound: try "speaker-test -t sine -l 1"

Decoding is done by the target CPU in every mode (FFmpeg's software
decoders); no video decoding is handed to the host.

### Audio

Target software plays on ALSA's `default` device. Where that sound goes is
the `audio` driver feature's strategy:

| Strategy | VM mode | Container mode |
|---|---|---|
| `host` (the default) | QEMU's emulated sound card (virtio-sound) with the target kernel's driver; the card's backend hands the samples to the launcher's host-side audio process | a shim ALSA device ([target/src/emu_alsa.c](target/src/emu_alsa.c)) sends the samples to that process over TCP |
| `emulated` | the same sound card with no backend: the kernel's driver plays to nowhere | a software model of a sound card: the same ALSA device, playing to nowhere at the sample rate |
| `mocked` | no sound card; a stub ALSA device discards the samples | the same stub |

The host-side audio process plays the sound with a player program, so it
goes wherever the host's sound system sends an application's sound. On Linux
that is the host's own `pacat`, `pw-cat` or `aplay`, whichever is installed.
macOS has no such program, so the launcher builds one the first time it is
needed ([emulator/coreaudio_player.c](emulator/coreaudio_player.c), into
`build/host/`); it plays through a Core Audio queue.
`--option audio-sink=NAME` chooses the host's output device, and
`--option audio-output=none` takes the sound in without playing it. On macOS
`--option audio-volume=0..100` sets the volume, and `build/host/emu-coreaudio
devices` lists the output devices.

Mute while it runs, from another terminal:

    ./emu audio mute | unmute | toggle | status

`./emu run --mute` starts muted. A muted emulator keeps playing: the target
notices nothing, and the host gets silence in place of the sound.

Limits:

- Playing through the host is implemented for Linux and macOS hosts. On
  Windows the audio process starts without a player and says so; the target's
  sound is taken in, and can be muted and inspected, but is not heard.
- On macOS the checks play at volume 0 and record what the system's audio
  queue takes for the output device; nobody has listened to it there yet.
- In VM mode QEMU writes the sound card's output into a named pipe. Windows
  has none of the kind QEMU can write to, so there the launcher falls back to
  the container mode's shim device over QEMU's network; that path has not
  been run.
- One player at a time: sound from two target programs playing at once is not
  mixed.
- ARM32 VM mode: no video through Vulkan or Flutter, for the reasons given
  under [Target OS image](#target-os-image). The Wayland compositor also ends
  now and then during playback there; the workload starts it again, plays the
  stream once more, and says so in the result.
- The Flutter application gets its video as decoded frames and turns each one
  into an image, which is slow: at 720p it shows about a third of a 25
  frames/s stream, also with host graphics. A Flutter application that shows
  video the way real ones do, through a texture that a native plugin fills,
  is not part of this.
- mpv's OpenGL ES and Vulkan outputs use its plain rendering path
  (`--gpu-dumb-mode`). With its default path, Mesa's CPU renderer showed a
  black or green picture in many runs.

## Evaluation

- [evaluation/matrix.json](evaluation/matrix.json): the hosts and modes to cover.
- [evaluation/workloads.json](evaluation/workloads.json): the versioned workloads.
- [evaluation/procedures.md](evaluation/procedures.md): how measurements are made.
- `evaluation/results/`: recorded results (`./emu run ... --record`), and a
  page that shows them as charts (see below).
- `evaluation/verification/`: what `./emu verify` has confirmed, per host.

### Results page

    ./emu report [--port N] [--no-browser]

starts a small web server for `evaluation/results/` on this machine only
(`http://127.0.0.1:8765/` unless `--port` says otherwise) and opens
[index.html](evaluation/results/index.html) in the default browser. It runs
until Ctrl-C. `--no-browser` only serves the page.

The page reads the JSON records itself each time it loads, so new runs appear
after a reload and nothing has to be regenerated. That is also why it needs
this server: a browser cannot list a directory, and an ordinary web server
does not list one that holds an `index.html`, so the launcher's server gives
the page the list of records. Opened another way (from disk, or from another
web server) the page asks for the results folder, or for its JSON files to be
dropped on it.

The page starts with the hosts the results were measured on: CPU, memory,
GPU with its driver, operating system and emulator software, as the records
describe them. (Records made before the launcher recorded the GPU name it only
where a test rendered on it.) [machines.json](evaluation/results/machines.json)
adds what was stated about each host's machine, such as its GPU where the
records do not have it; the page marks that as stated. Each test has a card with one row per host and emulator mode. A bar is the
median of that configuration's runs and the dots are the single runs. The
hosts can be filtered, values can be shown relative to the container on the
same host, and pointing at a row shows the details of its runs.

### Results as PDF

[emulator-results.pdf](evaluation/results/emulator-results.pdf) is a snapshot
of the charts; unlike the page it does not follow new runs. To make it again,
start `./emu report` and either print the page from the browser (Save as PDF;
the page has its own print layout, A4 landscape, charts only), or let Chrome
do it without a window:

    ./emu report --no-browser &
    google-chrome --headless=new --no-pdf-header-footer --virtual-time-budget=8000 \
        --print-to-pdf=evaluation/results/emulator-results.pdf http://127.0.0.1:8765/

`--virtual-time-budget` gives the page time to read the records before it is
printed. The PDF shows all hosts with measured values, the page's defaults.
This was run with Chrome on Linux; on macOS and Windows the browser's own
print dialog does the same. The snapshot in the repository was made on the
Linux host before the macOS media results were recorded, so it does not show
those; the page does.
