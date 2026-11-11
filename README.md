# emulator-evaluation

This repo contains an evaluation of various technologies for a device emulator.

The requirements live in the [openspec](openspec) folder. Delivery is staged
([tasks](openspec/changes/staged-emulator-delivery/tasks.md)); this repo
holds the code for stages 0 to 3: the evaluation foundation, a cross-platform
runnable baseline, VM CPU and driver fidelity, and graphics. So far they are
verified on one host, macOS on ARM64; Linux and Windows hosts have not been
run yet. The task list and `evaluation/verification/` show what has been
verified, and on which hosts.

## Quick start

    ./setup.sh              # Linux and macOS: check and install host dependencies
    ./emu run               # interactive prompt on the target OS, container mode
    ./emu run --mode vm     # the same in a host-native VM
    ./emu run --mode vm --workload graphics-demo --screenshot shots   # graphics, with display captures

On Windows use `.\setup.ps1` and `emu.cmd`.

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
| QEMU OpenGL modules (optional) | mapping VM graphics to the host GPU | not in Homebrew's QEMU | system package | not checked yet |

An existing Docker or Podman installation is used as it is.

The launcher starts a stopped container engine itself. On macOS, restarting
Colima drops the ARM32 build emulation; `./setup.sh` restores it, and it is
only needed to rebuild the ARM32 image.

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

On this project's only verified host (macOS on ARM64) neither mode has host
acceleration: Homebrew's QEMU is built without the GPU-accelerated display
device, and the container engine's virtual machine has no GPU. Both therefore
run emulated graphics, and the host-acceleration path is implemented but has
never been run. `./emu doctor` shows what a host offers.

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
