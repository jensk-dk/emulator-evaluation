# Disk space and times

Besides the performance results, the report has to state what the platform
costs on each host: the disk space of the host installation and of each
target, and the time that installing, building and running the performance
evaluation take
([requirement](../openspec/specs/performance-reporting/spec.md), task 8.3 of
the [task list](../openspec/changes/staged-emulator-delivery/tasks.md)).

**Only a few values are measured so far.** A value is filled in when a task
provides it, with the date and how it was taken. Until then it reads "not
measured", and the report shows it as unavailable. No value is estimated.

## What each value is

Proposed, not agreed; to be settled when the first values are taken.

- **Host installation, disk space.** What the setup script (`setup.sh`,
  `setup.ps1`) installed on the host, as its record lists it, together with
  what that software keeps for the project: for one, the container runtime's
  own virtual machine where it has one.
- **Host installation, time.** The setup script's running time on a host that
  had none of it installed. Downloads are part of it, so the value is given
  with the host's network connection.
- **Target, disk space.** One value per target the host builds: the container
  image, and the VM image of each guest CPU architecture (root file system,
  kernel and initial RAM disk).
- **Target, build time.** The running time of `./emu build` for that target
  from an empty build cache. Downloads are part of this one too.
- **Performance evaluation, time.** The running time of the performance
  workloads in one mode, each from launch to exit, the target's start
  included. Each result record already has its run's `duration_seconds` and
  `boot_seconds`; they have not been added up.

## Values

A host gets a table when it is evaluated. The macOS x86-64 host of the matrix
has none yet.

### Linux x86-64

| What | Disk space | Time | Taken |
|---|---|---|---|
| Host installation | not measured | not measured | |
| of that: Qt for Python, in `build/host/gui` | 262 MB | not measured | 2026-11-15, `du -sm` after `./setup.sh` installed PySide6-Essentials 6.12.0 |
| Target: container image (x86-64) | not measured | not measured | |
| Target: VM image, x86-64 (host-native) | not measured | not measured | |
| Target: VM image, ARM64 | not measured | not measured | |
| Target: VM image, ARM32 | not measured | not measured | |
| Performance evaluation: container | | not measured | |
| Performance evaluation: VM, host-native | | not measured | |
| Performance evaluation: VM, ARM64 target | | not measured | |
| Performance evaluation: VM, ARM32 target | | not measured | |

### Windows x86-64

| What | Disk space | Time | Taken |
|---|---|---|---|
| Host installation | not measured | not measured | |
| of that: Qt for Python, in `build/host/gui` | 234 MB | not measured | 2026-11-15, `du -sh` after `setup.cmd` installed PySide6-Essentials 6.12.0 |
| Target: container image (x86-64) | not measured | not measured | |
| Target: VM image, x86-64 (host-native) | not measured | not measured | |
| Target: VM image, ARM64 | not measured | not measured | |
| Target: VM image, ARM32 | not measured | not measured | |
| Performance evaluation: container | | not measured | |
| Performance evaluation: VM, host-native | | not measured | |
| Performance evaluation: VM, ARM64 target | | not measured | |
| Performance evaluation: VM, ARM32 target | | not measured | |

### macOS ARM64

The host-native VM and the ARM64 target use the same VM image here.

| What | Disk space | Time | Taken |
|---|---|---|---|
| Host installation | not measured | not measured | |
| of that: Qt for Python, in `build/host/gui` | 329 MB | not measured | 2026-11-15, `du -sh` after `./setup.sh` installed PySide6-Essentials 6.10.3 |
| Target: container image (ARM64) | 1.54 GB | not measured | 2026-11-15, image 0.6.0, as `docker image ls` lists it (its layers as stored compressed: 407 MB, `docker image inspect`) |
| Target: VM image, ARM64 (host-native and ARM64 target) | 1.95 GB | not measured | 2026-11-15, image 0.6.0, the sizes of its three files in `build/vm/arm64` added (`ls -l`): root file system 1.90 GB, kernel 38 MB, initial RAM disk 10 MB |
| Target: VM image, ARM32 | 1.49 GB | not measured | 2026-11-15, image 0.6.0, the same in `build/vm/arm32`: root file system 1.47 GB, kernel 6 MB, initial RAM disk 9 MB |
| Performance evaluation: container | | not measured | |
| Performance evaluation: VM, host-native | | not measured | |
| Performance evaluation: VM, ARM64 target | | not measured | |
| Performance evaluation: VM, ARM32 target | | not measured | |

The three target sizes are of image 0.6.0 as built on this host on
2026-11-15. No build time is given: these builds had the build cache of image
0.5.0 (they took 39 s, 45 s and 107 s), and the value wanted is the time from
an empty cache. Not counted above: the image that a VM image is exported
from stays in the container engine (2.5 GB for ARM64 and 1.93 GB for ARM32,
as `docker image ls` lists them), and so do the images of earlier versions
until they are removed.
