# emulator-evaluation

<picture>
  <img alt="Emu Device Emulator" src="docs/emu-logo.svg">
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
holds the code for stages 0 to 3: the evaluation foundation, a cross-platform
runnable baseline, VM CPU and driver fidelity, and graphics. So far they are
verified on two hosts: macOS on ARM64, and Windows on x86-64 with Podman as
the container runtime. Linux hosts have not been run yet. The task list and
`evaluation/verification/` show what has been verified, and on which hosts.

## Quick start

    ./setup.sh              # Linux and macOS: check and install host dependencies
    ./emu run               # interactive prompt on the target OS, container mode
    ./emu run --mode vm     # the same in a host-native VM
    ./emu run --mode vm --workload graphics-demo --screenshot shots   # graphics, with display captures

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
| QEMU OpenGL modules (optional) | mapping VM graphics to the host GPU | not in Homebrew's QEMU | system package | in winget's QEMU, but not usable yet (see [Display and graphics](#display-and-graphics)) |

An existing Docker or Podman installation is used as it is. Where both are
installed, Docker is used when its engine answers. To choose, set the
environment variable `EMU_CONTAINER_RUNTIME` to `podman` or `docker`; the
launcher and `setup.ps1` read it.

The launcher starts a stopped container engine itself. On macOS, restarting
Colima drops the ARM32 build emulation; `./setup.sh` restores it, and it is
only needed to rebuild the ARM32 image.

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
              [--driver FEATURE=STRATEGY] [--option KEY=VALUE] [--screenshot DIR]
              [--record] [--repeat N] [-- WORKLOAD_ARGS]

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
benchmarks), `driver-check` and `graphics-demo`. `./emu workloads` lists
them, including the media and web workloads that are defined for later
stages.

Other commands: `./emu build`, `./emu doctor`, `./emu matrix`,
`./emu workloads`, `./emu verify`. Each has `--help`.

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
These are choices for the evaluation image, not statements about the real
target's middleware.

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

The first feature is `hwrng`, the hardware random number generator at
`/dev/hwrng`. The host halves are in [emulator/drivers.py](emulator/drivers.py)
and [emulator/hostd.py](emulator/hostd.py); the target halves in
[target/rootfs/opt/emu/drivers](target/rootfs/opt/emu/drivers).

In container mode the shim reaches the host-side process over the network.
Podman's engine on Windows has no route to a process on Windows' loopback
address, so there a relay container on the engine's network carries the
connections to the host over its standard streams
([emulator/relay.py](emulator/relay.py)). No firewall rule or WSL setting is
involved.

## Display and graphics

The emulator has a display when the workload uses one, or when `--resolution`
or `--graphics` is given. `--resolution` selects 720p, 1080p (the default) or
4K.

| | VM mode | Container mode |
|---|---|---|
| Display | QEMU's emulated display adapter, driven by the target kernel's DRM/KMS driver | none; the compositor renders to a headless output of the selected size |
| `--graphics emulated` | the target CPU renders OpenGL ES and Vulkan (Mesa llvmpipe and lavapipe) | the same |
| `--graphics host` | QEMU's virtio-gpu maps OpenGL ES, and Vulkan where QEMU offers it, to the host GPU | the container gets the engine's GPU render node (`/dev/dri`) |

`--graphics auto`, the default, uses host acceleration when the host has a
compatible one and otherwise emulates; the launcher prints which it chose and
why. `--graphics host` fails rather than silently emulating.

Neither verified host has usable host acceleration yet, so both run emulated
graphics. `./emu doctor` shows what a host offers.

- macOS on ARM64: Homebrew's QEMU is built without the GPU-accelerated display
  device, and the container engine's virtual machine has no GPU.
- Windows on x86-64, VM mode: QEMU has the device, and with it the target
  renders OpenGL ES and Flutter on the host GPU (seen with QEMU 11.1.0 on an
  NVIDIA GPU: Flutter at 50 frames/s, against 18 emulated). But the display
  QEMU offers for it without a window (`egl-headless`) stays black, so no frame
  reaches the emulator's display. The launcher therefore reports host
  acceleration as unavailable on Windows and emulates. A windowed display, a
  later stage, may change that.
- Windows on x86-64, container mode: Podman's engine in WSL has no GPU render
  node.

The launcher captures a VM's display through QEMU's machine protocol. QEMU
refuses that while the display is a texture on the host GPU, so with host
acceleration the capture is read from QEMU's VNC server instead. That path
has only been run on Windows, where it returns the black display described
above; it is still to be run on a host where the display works.

`graphics-demo` runs a Wayland, an OpenGL ES, a Vulkan and a Flutter test.
`--screenshot DIR` saves a PNG of the emulator's display at the end of each
test. On the target, [`/opt/emu/display`](target/rootfs/opt/emu/display)
(`emu-display start`) starts the compositor, for running other Wayland
programs from the prompt.

## Evaluation

- [evaluation/matrix.json](evaluation/matrix.json): the hosts and modes to cover.
- [evaluation/workloads.json](evaluation/workloads.json): the versioned workloads.
- [evaluation/procedures.md](evaluation/procedures.md): how measurements are made.
- `evaluation/results/`: recorded results (`./emu run ... --record`).
- `evaluation/verification/`: what `./emu verify` has confirmed, per host.
