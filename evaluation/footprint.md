# Disk space and times

Besides the performance results, the report has to state what the platform
costs on each host: the disk space of the host installation and of each
target, and the time that installing, building and running the performance
evaluation take
([requirement](../openspec/specs/performance-reporting/spec.md), task 8.3 of
the [task list](../openspec/changes/staged-emulator-delivery/tasks.md)).

**The macOS and the Linux host are measured, and the Windows host but for
three build values that its disk had no room for.** A value is filled in when a
task provides it, with the date and how it was taken. Until then it reads
"not measured", and the report shows it as unavailable. No value is
estimated. How the values are taken is in the
[procedures](procedures.md#disk-space-and-times): since 2026-11-20 with
`python3 evaluation/measure.py run`, which keeps them in
`evaluation/footprint/HOST_MACHINE.json` and prints them as rows for a table
here (`measure.py table`). The tables below were taken by hand, before the
script.

Sizes are in decimal units (1 GB is 1000 MB, a thousand million bytes), as the
container engine and Finder give them; `du` counts in units of 1024, and its
values are converted.

## What each value is

Proposed, not agreed. The macOS values of 2026-11-16, the Windows values
of 2026-11-16 and 17 and the Linux values of 2026-11-17 and of 2026-11-18
and 19 were taken as written here; where taking them made a definition more exact than it was, that is now
part of it, and still to be agreed.

Since 2026-11-17 the setup scripts set a host up for the simulated ARM64 and
ARM32 targets only when asked to (`./setup.sh --arm-targets`,
`setup.cmd -ArmTargets`). The installation values of the macOS and the
Windows host were taken before that, with a setup script that installed what
those targets need without being asked, and those of the Linux host on
2026-11-18 with the option: all are the values of a setup with the option. A
setup without it has not been measured on any host. The sizes and build times of the
targets are not affected.

- **Host installation, disk space.** What the setup script (`setup.sh`,
  `setup.ps1`) installed on the host, as its record lists it, together with
  what that software keeps for the project: the container runtime's own
  virtual machine where it has one, and the downloads its tools keep. Two
  values, because the container engine's storage grows with what is built in
  it: right after the setup script, and with each of the host's targets built
  once. It is the sizes of the places the installation uses, added up, and
  checked against the growth of the used space on the volume.
- **Host installation, time.** The setup script's running time (with `--yes`,
  so that it waits for no answer) on a host from which its `--uninstall` had
  removed what that removes, and the tools' kept downloads besides. What the
  removal leaves in place is not installed again; it is named with the value.
  Downloads are part of the time, so the value is given with the host's
  network connection.
- **Target, disk space.** One value per target the host builds: the container
  image as the container engine lists it, and the VM image of each guest CPU
  architecture as the sizes of its files added (root file system, kernel and
  initial RAM disk).
- **Target, build time.** The running time of `./emu build --rebuild` for
  that target in a container engine that holds no image of the project and no
  build cache. Downloads are part of this one too. The targets share build
  steps, so a target built after another takes less: the time of all of a
  host's targets, built one after the other in a new engine, is given beside
  them.
- **Performance evaluation, time.** The running time of the performance
  workloads in one mode, each from launch to exit, the target's start
  included. It is added up from the result records, which have each run's
  `duration_seconds`: `python3 evaluation/footprint.py times` prints the sums.
  Two values per mode: one run of each of the four workloads (the sum of each
  workload's median run), and all the runs the host has recorded in that mode
  (the procedures ask for three of each workload; some hosts have recorded
  more, a workload at two versions or with two graphics providers).

## Values

A host gets a table when it is evaluated. The macOS x86-64 host of the matrix
has none yet. The results page and its PDF show these tables as they are
(`./emu report`): one table per host, under a heading with the host's name,
and before it what is to be said about that host's values as a whole.

### Linux x86-64

Installation, targets and builds were measured again on 2026-11-18 and 19 on
the Linux host (Intel Core i7-10700K, Ubuntu 24.04.5, Linux 6.8.0), after
the project had been renamed to tv-emu, with image 0.6.0 and a connection
of 86 Mbit/s down (one download of 100 MB with `curl`, at 10.7 MB/s,
minutes before the setup). The host had no installation when the
measurement began: no QEMU, no ARM build emulation, no Python environment
with Qt, and no record of the setup script, which is kept under the
project's new name. So nothing was removed for it but the kept downloads
and, from the container engine, the project's images and build cache. The
container engine is this host's own Docker 20.10.18, which was left in
place. The values of 2026-11-17, which these replace, are named beside
them.

| What | Disk space | Time | Taken |
|---|---|---|---|
| Host installation | 1.22 GB after `./setup.sh --arm-targets`; 25.9 GB with the four targets built once | 1.2 min | 2026-11-18, `./setup.sh --yes --arm-targets`, 74.9 s from its start to its end, with `sudo` needing no password. The space is the places below added (`du -sk`); the used space on the volume grew by 1.37 GB (`df -k`). With the option that also sets the host up for the simulated ARM targets; a setup without it is not measured. On 2026-11-17: 82.5 s and 1.22 GB |
| of that: QEMU 8.2.2 and the ARM build emulation, 32 packages of Ubuntu | 0.80 GB | 1.0 min | `apt-get update` 4.7 s (11.3 MB of package lists), `apt-get install` 56.1 s, 45 s of that downloading 58.9 MB (at 1.3 MB/s from the package server). The sizes of the packages' files added: the system emulators with their firmware 630 MB, the user-mode emulators that image builds run ARM programs with 137 MB, libraries 32 MB |
| of that: Qt for Python, in `build/host/gui` | 274 MB | 0.2 min | 12 s: the Python environment 2.4 s, PySide6-Essentials 6.12.0 9.4 s |
| of that: downloads the tools keep | 144 MB | | pip 85 MB in `~/.cache/pip`, apt 59 MB in `/var/cache/apt/archives` |
| of that: what the container engine holds, in `/var/lib/docker` | nothing new; 24.6 GB with the four targets built once | | the engine was there before. `sudo du -sk`, the growth from the engine without an image or a build step of the project |
| Target: container image (x86-64) | 1.11 GB | 3.9 min | 2026-11-18, 236 s from an engine without the project's images and build cache. Size as `docker image ls` lists it. On 2026-11-17: 230 s |
| Target: VM image, x86-64 (host-native) | 1.86 GB | 4.3 min | 256 s, likewise. The sizes of its three files in `build/vm/x86_64` added: root file system 1.84 GB, kernel 12 MB, initial RAM disk 10 MB. On 2026-11-17: 252 s |
| Target: VM image, ARM64 | 1.95 GB | 33.0 min | 1983 s, likewise. The same in `build/vm/arm64`: root file system 1.90 GB, kernel 38 MB, initial RAM disk 10 MB. On 2026-11-17: 1953 s |
| Target: VM image, ARM32 | 1.49 GB | 9.1 min | 544 s, likewise. The same in `build/vm/arm32`: root file system 1.47 GB, kernel 6 MB, initial RAM disk 9 MB. On 2026-11-17: 535 s |
| All four targets, one after the other in an emptied engine | | 46.3 min | 2026-11-18 and 19, 2777 s: the container image 231 s, then the host-native VM image 44 s (30 of its steps from the cache), then the ARM64 VM image 1968 s (5 from the cache), then the ARM32 VM image 534 s (5 from the cache). On 2026-11-17: 45.8 min |
| Performance evaluation: container | | 2.9 min for one run of each workload; 17.4 min for the 24 recorded runs | runs recorded 2026-11-12 to 19 (images 0.2.0 to 0.6.0), added up by `evaluation/footprint.py times`. Of those, the 12 runs of 2026-11-19 on the new installation with image 0.6.0: 8.8 min |
| Performance evaluation: VM, host-native | | 2.9 min for one run of each workload; 19.3 min for the 28 recorded runs | runs recorded 2026-11-12 to 19 (images 0.2.0 to 0.6.0), added up by `evaluation/footprint.py times`. Of those, the 12 runs of 2026-11-19 on the new installation with image 0.6.0: 8.8 min |
| Performance evaluation: VM, ARM64 target | | 10.4 min for one run of each workload; 67.8 min for the 27 recorded runs | runs recorded 2026-11-12 to 19 (images 0.2.0 to 0.6.0), added up by `evaluation/footprint.py times`. Of those, the 12 runs of 2026-11-19 on the new installation with image 0.6.0: 30.8 min |
| Performance evaluation: VM, ARM32 target | | 10.9 min for one run of each workload; 85.0 min for the 27 recorded runs | runs recorded 2026-11-12 to 19 (images 0.2.0 to 0.6.0), added up by `evaluation/footprint.py times`. Of those, the 12 runs of 2026-11-19 on the new installation with image 0.6.0: 32.3 min |
| Performance evaluation: the four modes, one after the other | | 80.7 min for the 48 runs | 2026-11-19, the runs on the new installation named above: 4840 s from the first launch to the last exit. On 2026-11-17, not recorded: 79.3 min |

What the values leave out, and what taking them showed:

- **What was left in place is not in the installation's values.** Docker
  (docker-ce 20.10.18 with buildx, from Docker's own package source), Python
  3.12.3 with its module for environments, the sound server with its player
  (`pacat`) and the libraries that Qt loads were there before and after. On
  a host without them `setup.sh` installs Podman, Python, the player and
  those libraries with apt; what they take and how long was not measured.
  Two more QEMU packages were on the host throughout (`ovmf`, `virtiofsd`).
- **Nothing was removed by the script this time.** The host had been left
  without the installation, and `./setup.sh --uninstall --check` found no
  record under the project's new name
  (`~/.local/state/tv-emu/setup-installed`), so it had nothing to remove.
  How the installation of 2026-11-17 was taken off the host was not
  observed. Removed for the measurement: apt's kept downloads (`apt-get
  clean`), the project's four images, and the engine's whole build cache
  (18.9 GB); pip's kept downloads (335 MB, of
  other projects' packages too) were moved aside and put back after it. The
  setup installed the 32 packages that it installed on 2026-11-17, and its
  record lists them and the Python environment.
- **The places added are 0.15 GB less than the volume's growth** (1.22
  against 1.37 GB). `apt-get update` fetched 11.3 MB of package lists, which
  are kept unpacked outside the places counted; what the rest is was not
  looked into. On 2026-11-17 the two agreed.
- **Most of the installation's time is one slow download**, as on
  2026-11-17. The package server gave the 58.9 MB of QEMU at 1.3 MB/s, an
  eighth of what the connection gave minutes before; the 84 MB of Qt came
  at 10.7 MB/s.
- **Each build from an emptied engine took no step from the cache** (its
  log has none marked `CACHED`). Emptied means: the project's images, the
  untagged images its builds left, the Debian base image and the engine's
  whole build cache removed; other images of the host's owner stayed (8.5
  GB), and no build uses them. On Linux the engine keeps its storage in a
  directory, so removing gives the space back, and one engine served all
  the builds. The ARM64 image takes eight times as long as the host-native
  one because its build steps run ARM programs under emulation, among them
  the compilation of the Flutter application; the ARM32 image has no Flutter
  application.
- **The build times are those of 2026-11-17 within 3 %**: each target alone
  took 4 to 30 s longer, all four together half a minute longer.
- **The build cache is where the space goes.** With the four targets built
  once the engine holds 24.6 GB more than without them: 6.4 GB of images
  (the container image and the three that the VM images are exported from)
  and 18.9 GB of build cache, by `docker system df`. One target alone took
  5.1 GB (container image), 9.8 GB (host-native VM image), 10.1 GB (ARM64)
  and 5.9 GB (ARM32). The VM images themselves are in the repository's
  `build/vm`, 5.29 GB, beside the installation.
- **Finding of 2026-11-17, changed the same day: nothing removed old images
  and build steps.** Before that measurement, after six days of builds for
  images 0.2.0 to 0.6.0, the engine held 106.7 GB of the project. A build
  now removes the images of other versions, the images a build of the same
  version took the tag from, and build steps unused for 48 hours (`./emu
  build --keep-old` does not). `./setup.sh --uninstall` still leaves the
  images of the current version where the engine was there before the
  setup.
- **Finding of 2026-11-17, corrected the same day: the setup script took
  the ARM build emulation for present when it was gone.** Where the engine
  runs on the host's own kernel the script now asks that kernel. This time
  `./setup.sh --check --arm-targets` named the emulation as missing before
  the setup, and the setup installed it.
- **The runs on the new installation are recorded this time.** The 48 runs
  of 2026-11-19 are in `evaluation/results/` with the earlier ones, and the
  results page shows them. They ran with `--mute`, so that no sound left
  the host, and all 48 ended normally. Of their 192
  values, 8 are unavailable in these and in the earlier runs (Vulkan and
  Flutter on the ARM32 target), and the median of 171 is within 10 % of the
  median of the runs recorded before, which are of images 0.2.0 to 0.5.0.
  Of the 13 further apart, seven are counts of dropped frames that differ
  by up to eight frames (ARM64 and ARM32 targets). The others: synchronous
  writing on the ARM64 target (1.29 of the earlier median) and on the ARM32
  target (1.47), the matrix multiplication on the ARM32 target (0.83),
  sequential reading in the host-native VM (1.12), OpenGL ES in the
  host-native VM (171 against 192 frames/s, as on 2026-11-17), and the
  decoding speed of the AVC stream on the ARM64 target (1.14).
- **The checks, measured along.** No requirement asks for their time: all
  140 checks of `./emu verify` took 66.0 min on the new installation
  (3961 s): 134 passed, 5 failed and 1 is not runnable on this host. Four
  of the failures are those of before (Vulkan and Flutter on the ARM32
  target), and the sixteen checks added since 2026-11-17 passed. The fifth
  is new: the STB simulator's start in container mode
  (`stb-start-container`) failed because the launcher's window did not save
  the display's picture. Run alone six more times, it failed once and
  passed five times, so the host's record has it as passed. The cause, found
  and corrected the same day: in container mode keys reach the target
  another way than through the window's connection to the display, so the
  user interface could take its first key before the window had the
  display's first picture, which came 0.4 s after the home screen in two
  runs of four. The check asked for the picture once and failed; it now
  waits for it. Six runs of the check and one of each other STB check in
  container mode then passed. The failure was the check's, not the
  simulator's.

### Windows x86-64

Installation, targets and builds were measured on 2026-11-16 and 17 on the
Windows PC (Intel Core i7-10700K, Windows 11 Pro 10.0.26300), after
`setup.cmd -Uninstall` and, by hand, `winget uninstall` had removed the
installation of 2026-11-11, with image 0.6.0 and a connection of 91 Mbit/s
down (one download of 100 MB with `curl`, at 11.3 MB/s, minutes after the
setup). The volume had 27 to 34 GB free, which was too little for three of
the build values: they read "not measured" for that, with what was seen
instead.

| What | Disk space | Time | Taken |
|---|---|---|---|
| Host installation | 3.96 GB after `setup.cmd`; with the four targets built once in one engine: not measured (19.4 GB with the engine that the checks and the runs below used, see the notes) | 3.2 min | 2026-11-16, `setup.cmd -Yes`, 189.5 s from its start to its end, two elevation prompts answered by a person included. The space is the places below added (the sizes of their files); the used space on the volume grew by 4.79 GB. Taken with the setup script as it was until 2026-11-17, which also installed what the simulated ARM targets need; that takes `--arm-targets` (`-ArmTargets`) now, and a setup without it is not measured |
| of that: QEMU 11.1.0, in `C:\Program Files\qemu` | 1.26 GB | 1.2 min | winget, 69 s by the times of the log's lines: 34 s downloading, 34 s installing, its elevation prompt included |
| of that: Podman 5.8.10, in `C:\Program Files\RedHat\Podman` | 71 MB | 0.2 min | winget, 14 s (6.5 s of that downloading), its elevation prompt included |
| of that: the container engine's VM (Podman's machine, on WSL 2), in `~\.local\share\containers` | 2.31 GB new; 17.7 GB with the engine that the checks and the runs below used | 0.9 min | created and started in 46 s, 8 s more to register the ARM emulation that image builds need. New: its disk (`ext4.vhdx`) 1.25 GB, the machine image 0.81 GB, and the download of it that Podman keeps, 249 MB |
| of that: Qt for Python, in `build/host/gui` | 237 MB | 0.4 min | 23 s: the Python environment 9 s, PySide6-Essentials 6.12.0 14 s |
| of that: downloads pip keeps, in `%LOCALAPPDATA%\pip\Cache` | 83 MB | | |
| Target: container image (x86-64) | 1.11 GB | 8.4 min | 2026-11-16, 502 s from an empty engine. Size as `podman image ls` lists it |
| Target: VM image, x86-64 (host-native) | 1.86 GB | not measured | Two builds from an empty engine filled the volume at their last step and failed, after 633 s and 631 s. Built after the container image in the same engine: 150 s on 2026-11-15 (39 of its steps from the cache). The sizes of its three files in `build/vm/x86_64` added: root file system 1.84 GB, kernel 12 MB, initial RAM disk 10 MB |
| Target: VM image, ARM64 | 1.95 GB | not measured | The build from an empty engine filled the volume at its last step and failed, after 2332 s. A build of 2026-11-15 in a new engine that held the container image only, without `--rebuild` and with no step from the cache, took 38.1 min (2286 s). The same in `build/vm/arm64`: root file system 1.90 GB, kernel 38 MB, initial RAM disk 10 MB |
| Target: VM image, ARM32 | 1.49 GB | 20.1 min | 2026-11-16, 1207 s from an empty engine. The same in `build/vm/arm32`: root file system 1.47 GB, kernel 6 MB, initial RAM disk 9 MB |
| All four targets, one after the other in a new engine | | not measured | the volume has too little free space for it: the build of one target alone took up to 27 GB of it |
| Performance evaluation: container | | 3.0 min for one run of each workload; 10.9 min for the 16 recorded runs | runs recorded 2026-11-11 to 15 (images 0.2.0 to 0.5.0), added up by `evaluation/footprint.py times`. Run again on 2026-11-17 on the new installation with image 0.6.0, not recorded: 3.0 min, and 9.0 min for 12 runs |
| Performance evaluation: VM, host-native | | 3.2 min for one run of each workload; 11.6 min for the 16 recorded runs | runs recorded 2026-11-11 to 15 (images 0.2.0 to 0.5.0), added up by `evaluation/footprint.py times`. Run again on 2026-11-17 on the new installation with image 0.6.0, not recorded: 3.2 min, and 9.5 min for 12 runs |
| Performance evaluation: VM, ARM64 target | | 15.9 min for one run of each workload; 61.3 min for the 15 recorded runs | runs recorded 2026-11-11 to 15 (images 0.2.0 to 0.5.0), added up by `evaluation/footprint.py times`. Run again on 2026-11-17 on the new installation with image 0.6.0, not recorded: 16.0 min, and 48.0 min for 12 runs |
| Performance evaluation: VM, ARM32 target | | 31.2 min for one run of each workload; 102.2 min for the 15 recorded runs | runs recorded 2026-11-11 to 15 (images 0.2.0 to 0.5.0), added up by `evaluation/footprint.py times`. Run again on 2026-11-17 on the new installation with image 0.6.0, not recorded: 20.9 min, and 62.7 min for 12 runs |
| Performance evaluation: the four modes, one after the other | | 133.6 min for the 48 runs | 2026-11-17, the runs on the new installation named above: 8017 s from the first launch to the last exit |

What the values leave out, and what taking them showed:

- **What was left in place is not in the installation's values.** Python
  3.13.1, WSL 2, the Windows Hypervisor Platform and winget were there
  before and after: `setup.cmd` installs them on a host that lacks them, and
  its `-Uninstall` removes only what its record lists. That record began
  after this host was set up, so it did not list QEMU and Podman either;
  those two were removed with `winget uninstall` by hand, and the setup
  installed them. Podman came back as 5.8.10, where 5.8.9 had been.
- **The time has a person in it.** The installers of QEMU and of Podman each
  ask for elevation, and `-Yes` does not answer that. Both prompts were
  answered at once; the time they waited is in the 189.5 s and was not
  taken apart.
- **The places added are 0.83 GB less than the volume's growth** (3.96
  against 4.79 GB). What the rest is was not found; WSL and Windows keep
  files of their own outside the places counted.
- **Finding: a build needs far more of the volume than its images hold, and
  the space does not come back.** Podman's machine keeps its storage in a
  disk file (`ext4.vhdx`) that only grows: removing images and the build
  cache frees space inside the machine, not on the volume, and a build that
  follows does not use the freed space first. The container image's build
  took the file from 1.25 to 11.45 GB, with 4.95 GB of images in the engine
  afterwards. The host-native VM image's build in the same engine, emptied,
  took it to 22.6 GB and the volume to 0 bytes free; alone in a new machine
  it filled the volume again, from 27.5 GB free. The ARM64 build, alone in a
  new machine with 30.2 GB free, did the same. The ARM32 build took 19.7 GB
  of the volume. Only removing the machine gives the space back.
- **Finding: a full volume breaks Podman's machine.** After each of the
  three failures the machine no longer started and `podman machine rm` could
  not remove it. `wsl --unregister podman-machine-default` removed its
  distribution, and a second `podman machine rm --force` Podman's record of
  it, without which `setup.cmd` fails with `WSL_E_DISTRO_NOT_FOUND`;
  `setup.cmd -Yes` then made a new machine, in 45 to 66 s (five times).
- **The targets as they are now were built without kept layers.** To get all
  four images onto this volume, the ARM64 image, the container image and the
  host-native VM image were built again with `BUILDAH_LAYERS=false` in the
  environment, which keeps no intermediate layer and so no build cache.
  That is not the build the definition names, so these are not the table's
  values: ARM64 36.1 min (2169 s; the disk file reached 15.6 GB), the
  container image 6.3 min (379 s; 9.1 GB), and after it in the same engine
  the host-native VM image 7.6 min (457 s, no step from the cache;
  16.7 GB). The 19.4 GB and 17.7 GB in the table are of that last engine,
  which holds the container image and the image that the host-native VM
  image was exported from (3.25 GB as `podman image ls` lists them). The VM
  images are in the repository's `build/vm`, 5.29 GB, beside the
  installation.
- **The builds of 2026-11-15** that two rows name were made for the checks,
  not for this measurement, each in a new machine, with Podman 5.8.9 and
  image 0.6.0: the container image in 405 s, the host-native VM image after
  it in 150 s, the ARM64 image in 2286 s and the ARM32 image in 1222 s. The
  engine of the last two held the container image, loaded from a file.
- **The container image's build reused one step** (its log has one line
  `Using cache`, for a step the same build had made); the ARM32 build's log
  has none.
- **The removal.** `setup.cmd -Uninstall -Yes` took 11.7 s and freed 4.96 GB
  on the volume: the ARM emulation's registration and image, Podman's
  machine and the Python environment with Qt. Removing the machine ended
  with an error (`podman machine rm`, status 125, over a socket file it
  could not delete); the machine was gone all the same, and the script went
  on. Left behind and removed by hand: the 249 MB download that Podman
  keeps of its machine image, and pip's kept downloads (165 MB). QEMU's own
  uninstaller left four programs and an empty folder in
  `C:\Program Files\qemu` (6 MB).
- **The runs on the new installation are not results.** They were made to
  see that the installation as measured performs like the one the results
  were recorded on, and they are not in `evaluation/results/`. All 48 ended
  normally. Of their 192 values, 8 are unavailable in both (Vulkan and
  Flutter on the ARM32 target), and the median of 164 is within 10 % of the
  recorded median, though the recorded runs are of images 0.2.0 to 0.5.0
  and these of 0.6.0. Of the 20 further apart, 18 are on the ARM32 target:
  all 14 decoding speeds are 1.36 to 1.61 times the recorded ones (image
  0.3.0), and that workload's run takes 13.7 min where 23.4 min is
  recorded, which is why one run of each workload takes 20.9 min against
  31.2; the frames dropped in the Wayland playback of the three streams are
  more (95, 77 and 75 of 125, against 74, 68 and 68); and the web page
  renders at 0.07 frames/s against 0.05. Why the ARM32 target decodes
  faster now was not looked into. The other two are sequential writing, in
  container mode (0.70 of the recorded) and on the ARM64 target (0.87).
- **The checks, measured along.** No requirement asks for their time: all
  124 checks of `./emu verify` took 116.6 min on the new installation
  (6997 s): 116 passed, 6 failed and 2 are not runnable on this host, the
  numbers from before the removal. Two checks came out differently, though.
  The web page check on the ARM32 target failed, with a black capture; run
  again twice, it passed both times, as it had before. The video on demand
  check on the ARM64 target passed, and twice more after that, where it had
  failed in two runs out of two on 2026-11-15; its image was built anew in
  between, from the same definition. What made the difference is not known;
  it is with the known issues of the results page.

### macOS ARM64

The host-native VM and the ARM64 target use the same VM image here, so the
host builds three targets. Installation, targets and builds were measured on
2026-11-16 on the Mac mini (Apple M6, macOS 27.2.1), after
`./setup.sh --uninstall` had removed the installation of 2026-11-11, with
image 0.6.0 and a connection of 86 Mbit/s down (`networkQuality`, the same
afternoon).

| What | Disk space | Time | Taken |
|---|---|---|---|
| Host installation | 3.8 GB after `./setup.sh`; 25.4 GB with the three targets built once | 4.4 min | 2026-11-16, `./setup.sh --yes`, 264 s from its start to its end. The space is the places below added (`du -sk`); the used space on the volume grew by 3.84 GB (`df -k`). Taken with the setup script as it was until 2026-11-17, which also installed what the simulated ARM targets need; that takes `--arm-targets` (`-ArmTargets`) now, and a setup without it is not measured |
| of that: Homebrew with QEMU 11.1.3, Colima 0.10.3, the Docker client 29.10.0 and buildx 0.39.0, in `/opt/homebrew` | 1.40 GB | 2.4 min | Homebrew itself 31 s, then its 34 packages 112 s (85 s of that downloading), by the times of the log's lines |
| of that: the container engine's VM (Colima), in `~/.colima` | 1.30 GB new; 22.9 GB with the three targets built once | 1.3 min | created and started in 75 s (54 s of that downloading its disk image), 5 s more to register the ARM32 emulation that image builds need |
| of that: Qt for Python, in `build/host/gui` | 345 MB | 0.5 min | 32 s, PySide6-Essentials 6.10.3 |
| of that: downloads the tools keep, in `~/Library/Caches` | 0.76 GB | | Homebrew 320 MB, Colima 336 MB, pip 107 MB |
| Target: container image (ARM64) | 1.54 GB | 3.1 min | 185 s from an empty engine. Size as `docker image ls` lists it (its layers as stored compressed: 407 MB, `docker image inspect`) |
| Target: VM image, ARM64 (host-native and ARM64 target) | 1.95 GB | 3.5 min | 210 s from an empty engine. The sizes of its three files in `build/vm/arm64` added: root file system 1.90 GB, kernel 38 MB, initial RAM disk 10 MB |
| Target: VM image, ARM32 | 1.49 GB | 4.8 min | 290 s from an empty engine. The same in `build/vm/arm32`: root file system 1.47 GB, kernel 6 MB, initial RAM disk 9 MB |
| All three targets, one after the other in a new engine | | 9.1 min | the container image 215 s, then the ARM64 VM image 53 s (30 of its steps from the cache), then the ARM32 VM image 277 s (5 from the cache) |
| Option: the experimental QEMU (`./setup.sh --experimental-qemu`) | 2.87 GB more: 0.64 GB in `/opt/homebrew`, 2.22 GB of downloads that Homebrew keeps in `~/Library/Caches/Homebrew` | 6.8 min | 2026-11-16, one run of 405 s, after the build, the 16 packages that came with it, its tap and all of Homebrew's downloads had been removed. Of that Homebrew gives as build time: `gn` 16 s, `libangle` 66 s, `libepoxy-angle` 6 s, `virglrenderer` 17 s, `qemu-virgl` 61 s; most of the rest is fetching sources. A first build that day, in three runs with two commits fetched by hand, took 7.0 min in all and 2.83 GB |
| Option: the x86-64 VM image for the diagnostic guest (`./emu build --mode vm --arch x86_64`); not a target of the matrix | 1.86 GB in `build/vm/x86_64`, and 11.4 GB more in the container engine's disk on the Mac | 6.7 min | 2026-11-17, one build of 399 s for another CPU architecture than the host's, in the engine that held the three targets, not in an emptied one; 5 of its steps from the cache. Root file system 1.84 GB, kernel 12 MB, initial RAM disk 10 MB. The engine's disk file grew from 23.96 GB to 35.40 GB (`du -sk`), its build cache from 16.7 GB to 26.6 GB (`docker system df`) |
| Performance evaluation: container | | 2.6 min for one run of each workload; 7.8 min for the 12 recorded runs | runs recorded 2026-11-11 to 15 (images 0.1.0 to 0.4.0), added up by `evaluation/footprint.py times`. Run again on 2026-11-16 on the new installation with image 0.6.0, not recorded: 2.6 min and 7.9 min |
| Performance evaluation: VM, host-native | | 2.6 min for one run of each workload; 7.9 min for the 12 recorded runs | runs recorded 2026-11-11 to 15 (images 0.1.0 to 0.4.0), added up by `evaluation/footprint.py times`. Run again on 2026-11-16 on the new installation with image 0.6.0, not recorded: 2.6 min and 7.9 min |
| Performance evaluation: VM, ARM64 target | | 5.5 min for one run of each workload; 16.5 min for the 12 recorded runs | runs recorded 2026-11-11 to 15 (images 0.1.0 to 0.4.0), added up by `evaluation/footprint.py times`. Run again on 2026-11-16 on the new installation with image 0.6.0, not recorded: 5.6 min and 16.9 min |
| Performance evaluation: VM, ARM32 target | | 7.0 min for one run of each workload; 20.9 min for the 12 recorded runs | runs recorded 2026-11-11 to 15 (images 0.1.0 to 0.4.0), added up by `evaluation/footprint.py times`. Run again on 2026-11-16 on the new installation with image 0.6.0, not recorded: 6.8 min and 20.6 min |
| Performance evaluation: the four modes, one after the other | | 53.4 min for the 48 runs | 2026-11-16, the runs on the new installation named above: 3202 s from the first launch to the last exit |

What the values leave out, and what taking them showed:

- **The Xcode Command Line Tools are not in the installation's values.**
  `setup.sh` has them installed (by Homebrew's installer) on a Mac that lacks
  them, and its `--uninstall` leaves them in place, so they were there:
  1.42 GB in `/Library/Developer/CommandLineTools`, installation time not
  measured. Nor is the time to type the administrator's password that
  Homebrew's installer asks for.
- **Each build from an empty engine took no step from the cache** (its log
  has none marked `CACHED`). The container image was built twice that way,
  in 185 s and 215 s; downloads are a large part of every build.
- **The engine's VM is where the space goes.** With the three targets built
  once, its data disk holds 21.3 GB (`df` inside the VM): the container
  image, the two images that the VM images are exported from (2.5 GB for
  ARM64 and 1.93 GB for ARM32, as `docker image ls` lists them), and the
  build cache (16.7 GB by `docker system df`, 12.3 GB of it reclaimable; it
  shares storage with the images). The VM images themselves are in the
  repository's `build/vm`, 3.43 GB, beside the installation.
- **Finding: the VM's disk on the Mac only grows.** Removing images and the
  build cache frees space inside the VM, not on the Mac: emptying the engine
  after the first build left `~/.colima` at the 7.8 GB it had, and the five
  builds of the measurement, the engine emptied before each of the first
  three, took it to 29.8 GB while its data disk held 21.3 GB. In the engine
  the values above are from, the checks and the 48 performance runs then
  added 2.2 GB on the Mac (22.9 to 25.1 GB), with the data disk still at
  21.3 GB. `setup.sh` gives that disk 60 GiB (64.4 GB), which is the limit.
  The installation of 2026-11-11 had reached 63.7 GB there after five days
  of builds; removing it freed 68.6 GB on the volume, in 22 s.
- **The runs on the new installation are not results.** They were made to
  see that the installation as measured performs like the one the results
  were recorded on, and they are not in `evaluation/results/`. All 48 ended
  normally. Of their 192 values, the median of 187 is within 10 % of the
  recorded median, though the recorded runs are of images 0.1.0 to 0.4.0 and
  these of 0.6.0. The five that are further apart: sequential writing in
  container mode (0.89 of the recorded), `malloc_churn` on the ARM32 target
  (0.90), and there the frames dropped in the Wayland playback of the three
  streams (81, 97 and 56 of 125, against 104, 80 and 98).
- **Finding, and changed the same day: the experimental QEMU's sources.** The
  forks it is built from had their branches rewritten on 2026-11-16
  (virglrenderer at 11:37, QEMU at 11:42), and the commits that `setup.sh`
  pins are on no branch any more. Homebrew's clone of a fork then lacks the
  commit, and the option stopped with `fatal: unable to read tree`. Both
  servers still gave the commits out by their ids. The first build was
  finished by fetching each by hand and running the option again. The script
  was then changed to do that itself, the build removed, and the value above
  taken from one run of the changed script; the build is of the same commits
  as before (QEMU 11.1.90, `c95b8c49`). In one run with `--window` the
  target reported OpenGL ES at 117 frames/s and Flutter at 60 on `virgl
  (ANGLE (Apple, Apple M6, OpenGL 4.1 Metal))`; such a display cannot be
  captured, so no picture was looked at.
- **The checks, measured along.** No requirement asks for their time: all
  124 checks of `./emu verify` took 42.6 min on the new installation (2554 s)
  and came out as before the removal, 118 passed, 4 failed and 2 not
  runnable on this host.
