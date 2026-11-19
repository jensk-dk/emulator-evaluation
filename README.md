# TV Emulator (tv-emu)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/emu-logo-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/emu-logo.svg">
  <img alt="Emu Device Emulator" src="docs/emu-logo.svg" width="150" height="150">
</picture>

This repo contains a generic device emulator for Linux-based TVs and set-top boxes. Features:

* Runs on Linux, Mac and Windows hosts.
* Setup script that can check or install required dependencies for each host OS.
* VM mode for development and Container mode for CI.
* Supports Wayland, OpenGL ES, Vulkan and Flutter graphics on target OS.
* Supports A/V decoding in emulator with common broadcast and broadband A/V formats and codecs
* Unified command line command regardless of the underlying emulator technology used.
* A settings window when started without arguments, a display window with a toolbar, and remote control keys from the keyboard, an on-screen remote control, or a host RedRat IR receiver with selectable learned remote profiles.
* Comprehensive performance analysis and reporting

The requirements live in the [openspec](openspec) folder. Delivery is staged
([tasks](openspec/changes/staged-emulator-delivery/tasks.md)); this repo
holds the code for stages 0 to 4: the evaluation foundation, a cross-platform
runnable baseline, VM CPU and driver fidelity, graphics, and media playback.
Stages 0 to 4 are verified on three hosts: macOS on ARM64, Windows on x86-64
with Podman as the container runtime, and Linux on x86-64 (Kubuntu 24.04)
with Docker. Stage 5, the WPE WebKit browser with its web workload, is
implemented and verified on all three: the browser
launches, renders the workload's page and plays the reference streams through
Media Source Extensions in every mode the image is built for, and the
workload's measurements are recorded for each host. Of stage 6, the
launcher's own windows are implemented and verified on all three hosts: the
display window (toolbar, scaling, full screen), remote control keys from the
host keyboard and from an on-screen remote control, and the settings window.
RedRat IR input has a host SDK bridge and guided remote learning; physical
remote-key delivery still needs hardware verification. The STB simulator is implemented and
verified on Linux and macOS and, except for video on demand in the ARM VMs,
on Windows ([STB simulator](#stb-simulator)). macOS has no host
graphics acceleration, which the Linux host has in VM mode. The task list and
`evaluation/verification/` show what has been verified, and on which hosts.

## Quick start

    ./setup.sh              # Linux and macOS: check and install host dependencies
    ./setup.sh --arm-targets   # the same, and what the simulated ARM64 and ARM32 targets need
    ./emu                   # a window with the settings below, and a Start button
    ./emu run               # interactive prompt on the target OS, container mode
    ./emu run --mode vm     # the same in a host-native VM
    ./emu run --mode vm --workload graphics-demo --screenshot shots   # graphics, with display captures
    ./emu run --mode vm --workload graphics-demo --window             # graphics, with the display in a window
    ./emu run --mode vm --workload media-decode --window              # decoding and playing video and sound
    ./emu run --workload remote-keys                                   # keyboard input; toggle the on-screen remote
    ./emu run --workload stb-simulator                                 # a set-top box: channels, apps, video on demand
    ./emu audio mute                                                  # from another terminal, while it plays

On Windows use `setup.cmd` and `emu.cmd`, and `setup.cmd -ArmTargets`.
(`setup.cmd` runs `setup.ps1` where the PowerShell execution policy does not
allow scripts, which is the default.)

The first run builds the target OS image, which downloads Debian packages and
takes a few minutes. Later runs start in seconds.

## Host setup

`setup.sh` (Linux, macOS) and `setup.ps1` (Windows) check for every host
dependency and install what is missing. `--check` / `-Check` only reports.
`--arm-targets` / `-ArmTargets` also sets up the simulated ARM targets (see
[The simulated ARM targets](#the-simulated-arm-targets)).
`--uninstall` / `-Uninstall` removes what they installed (see
[Removing what setup installed](#removing-what-setup-installed)). The setup
scripts build no target image: the launcher builds an image when it is first
needed.

| Dependency | Used for | macOS | Linux | Windows |
|---|---|---|---|---|
| Python 3.9+ | the launcher | Xcode Command Line Tools | system package | winget |
| QEMU system emulator for the host's own CPU | VM mode | Homebrew `qemu` | system package | winget |
| Hardware virtualization | host-native VM mode | Hypervisor.framework | KVM | Windows Hypervisor Platform |
| Container runtime | container mode, image builds | Colima + Docker CLI (Homebrew) | Podman | Podman |
| Qt for Python (`PySide6-Essentials`) | the launcher's windows: display window, on-screen remote control, settings window | pip, into a Python environment of the project's own (`build/host/gui`) | the same; the libraries Qt loads come as system packages | pip, into `build\host\gui` |
| RedRat SDK bridge | receiving IR and learning remote profiles | .NET 10 SDK in `build/host/dotnet`, RedRat NuGet package, Homebrew `libusb` | the same private SDK and package, system libusb/runtime libraries, active-desktop-user USB permission rule | private SDK and package, official RedRat USB driver (elevated installation wizard) |
| Audio player (optional) | playing the target's sound on the host | built by the launcher with the Command Line Tools' compiler | `pacat`, `pw-cat` or `aplay`; system package | the launcher's own, run by Python; nothing to install |
| QEMU OpenGL modules (optional) | mapping VM graphics to the host GPU | not in Homebrew's QEMU; an experimental build has them, installed only with `./setup.sh --experimental-qemu` (see [Experimental: host graphics on macOS](#experimental-host-graphics-on-macos)) | system package | in winget's QEMU; used when the display is in a window (see [Display and graphics](#display-and-graphics)) |

An existing Docker or Podman installation is used as it is. Where both are
installed, Docker is used when its engine answers. To choose, set the
environment variable `EMU_CONTAINER_RUNTIME` to `podman` or `docker`; the
launcher and `setup.ps1` read it.

The launcher starts a stopped container engine itself.

Setup keeps Qt for Python below 6.12 and replaces an incompatible installation
when rerun. PySide6 6.12.0 corrupts Python's `True` reference count during signal
delivery on Python 3.10, crashing display playback and sometimes learning at
shutdown. The same framebuffer regression passes with 6.11.3; the launcher
rejects the incompatible series before opening a window. This restriction
applies to the host GUI only, not the target images.

RedRat support is always installed, even when no receiver is connected. Setup
publishes the host helper into `build/host/redrat`; it builds no target image.
Only the RedRat input choice is disabled when no receiver is detected.
The SDK package's own license is supplied with its distribution; it is not
copied into this repository. Ordinary target runs do not need a receiver.

### The simulated ARM targets

The ARM64 and ARM32 guest CPU modes run on a simulated CPU. That is slow
(on the three hosts the browser drew its test page at 0.05 to 2.8 frames a
second there, against 26 to 61 in a host-native VM), and Vulkan and Flutter
do not run on the ARM32 target. So a host is not set up for them
by default. `./setup.sh --arm-targets` (`setup.cmd -ArmTargets`) checks for
what only they need and installs what is missing of it:

| Only with the option | Used for | macOS | Linux | Windows |
|---|---|---|---|---|
| QEMU's ARM system emulators | VM mode with an ARM64 or ARM32 guest | in Homebrew's `qemu`, which is one package | system package | in winget's QEMU, which is one package |
| ARM build emulation (binfmt) | building the ARM target images | registered in the engine VM | `qemu-user-static` | registered in the engine VM |

Without the option the setup scripts neither check for these nor report
them as missing; they say that the simulated ARM targets are not set up by
default, and name the option. What the option installs is in the record
like everything else, and `--uninstall` removes it.

On a host that is not set up for them, the launcher starts no build and no
VM for such a target. `./emu run --mode vm --arch arm32`, a build of that
image and `./emu verify` say that the target is not set up and name the
option; the checks for it end as "unavailable". `./emu doctor` says for each
of the two whether it is set up, and does not count it as a missing
dependency. Container mode and the host-native VM need none of this.

On an ARM64 host, such as the macOS host, the ARM64 target runs on the
emulator and the image of the host's own CPU, so only the ARM32 target needs
the option there, for the emulation that builds its image. On macOS,
restarting Colima drops that emulation; `./setup.sh --arm-targets` restores
it, and it is only needed to rebuild the ARM32 image.

Hosts that the evaluation is run on are set up with the option, since the
evaluation covers the ARM targets. Agents set up, build and verify with them
as well: [AGENTS.md](AGENTS.md) says so.

How far this has been run (2026-11-17):

- On the macOS host the ARM32 build emulation was taken out of the container
  engine, as a restart of Colima does. `./setup.sh --check` then found every
  dependency present, and with `--arm-targets` named the emulation as
  missing. The launcher refused to rebuild the ARM32 image, said why and
  named the option, and left the image as it was. `./setup.sh --arm-targets`
  put the emulation back.
- In an x86-64 Ubuntu 24.04 container on that host, `./setup.sh` installed
  `qemu-system-x86` and no ARM emulator, and with `--arm-targets` it added
  `qemu-system-arm`, which its record then listed. A container has no
  container engine of its own, so the build emulation was not tried there.
- The package lists for dnf, zypper and pacman were split in the same way
  and not run again.
- `setup.ps1` has not been run on Windows since the change. PowerShell on
  Linux read it without errors, and its new check gave the expected lines
  with stand-ins for the programs on the host.
- The launcher's answers for a host without the ARM32 emulator, and `./emu
  verify` ending the ARM32 checks as "unavailable", were tried on the macOS
  host with stand-ins; no build was started.
- Neither script has been run on the Linux or the Windows host since the
  change.

Qt is the one part of the launcher that is not Python's standard library. It
is installed with pip from the Python Package Index into a Python environment
of its own inside the repository, so the host's Python stays as it is; the
launcher itself runs without it, and says what is missing when a window is
asked for. On the macOS host the environment takes 329 MB. `EMU_GUI_PYTHON`
names another Python that has PySide6, to use in its place. pip picks the
newest version that fits the host's Python: 6.10.3 for the Python 3.9 of the
macOS host, 6.12.0 for the newer ones tried.

Installed and run on macOS and on Windows (`setup.cmd` installed version
6.12.0 for Python 3.13, 234 MB). On Linux the package lists were tried in
containers, not on a desktop: on Ubuntu 22.04 and 24.04, Fedora and openSUSE
Tumbleweed Qt installed, its X11 and Wayland plugins found their libraries
(looked at on the two Ubuntus), and the settings window ran without a
display. On Arch the installation stopped on a file conflict among the
image's own packages and was not carried further.

On the Linux host (Kubuntu 24.04, Python 3.12) `./setup.sh` installed version
6.12.0, 262 MB, and the windows run on its desktop (X11). The system packages
Qt needs were all there already. The script asks the package manager only
for those that are missing: asked for one that is installed, apt marks it as
installed on request, and it would then stay when the software it came with
is removed.

### Removing what setup installed

The setup scripts keep a record of what they install on a host: only of what
was not there before they put it there. `./setup.sh --uninstall`
(`setup.cmd -Uninstall` on Windows) lists what the record has, asks, and
removes it. With `--check` (`-Check`) it only lists.

- Packages are removed with the package manager that installed them. A
  package that something installed later has come to need stays, and the
  script says so.
- The record has every package an installation added: the packages the script
  asked for, and the packages that came with them as dependencies. Of those
  that came with them, each goes that nothing else uses. No other package
  goes, also not one that was installed as a dependency and that nothing
  needed before setup ran.
- On Linux the package manager is first asked what it would remove, and
  anything that is not in the record is held back. Homebrew is told not to
  remove unused dependencies on its own, as it does on every uninstall, and
  is asked which of the recorded ones nothing needs.
- A virtual machine the script created for the container engine (Colima's on
  macOS, Podman's machine on Windows) is deleted with every container, image
  and volume in it. On Linux the same goes for Podman's storage, where the
  script installed Podman. The target images the launcher built are among
  those.
- The experimental QEMU on macOS is removed with the rest, with its tap and
  Homebrew's trust in it. Homebrew keeps that trust outside itself, in
  `~/.homebrew/trust.json`, where its uninstaller leaves it: where Homebrew
  itself is removed, the script takes the trust back first, and gives it
  again should Homebrew stay.
- Where the script installed Homebrew itself, Homebrew was installed for this
  project, and all that is installed with it counts as this project's, also
  what was installed with it later by hand. The uninstall then removes
  Homebrew with its own uninstaller, and every package with it. The list
  names the packages that the script did not install before it asks.
  Homebrew's uninstaller asks for an administrator's password, so this needs
  a terminal; without one the script stops before it removes anything. A
  Homebrew that was there before setup stays, and only the recorded packages
  go.
- Some things are listed with the command that removes them, and left in
  place, because other software can have come to use them and removing them
  takes root rights. On macOS: the Xcode Command Line Tools that Homebrew's
  installer adds, and the developer directory that installer selects. On
  Windows: the Windows Hypervisor Platform feature and WSL 2.
- The Python environment with Qt, which the script creates in `build/host/gui`,
  is removed whole. A recorded environment that is not in a folder of that
  name stays.
- Apart from that, this repository is not touched, nor `build/` in it.

The record is `~/.local/state/tv-emu/setup-installed` (under
`$XDG_STATE_HOME` where that is set; on Windows
`%LOCALAPPDATA%\tv-emu\setup-installed`). It is a text file with
one line for each thing. A host that was set up before the scripts kept a
record has none, and there `--uninstall` finds nothing to remove.

How far this has been run:

- macOS: removing the Python environment with Qt was run on a stand-in, with
  a record made for the test: the stand-in went, and a folder of another name
  that the record also listed stayed.
- macOS: the script installed the experimental QEMU and removed it again,
  with its tap and the trust in it. It deleted a second Colima virtual
  machine made for the purpose, removed the ARM build emulation and its image
  from the container engine, and left a package in place that another one
  needs. With the experimental QEMU went the 16 Homebrew packages that came
  with it, and the 30 that Homebrew's QEMU and Colima use stayed. With two
  small packages that stood in for the script's own, a dependency from before
  setup stayed, which Homebrew's own uninstall would have removed. Removing
  Homebrew itself was not run then: its steps were run with stand-ins that
  remove nothing, and Homebrew's uninstaller in its dry-run mode.
- macOS: on 2026-11-16 the whole setup was removed from the Mac this was
  written on and installed again, for the
  [disk space and time values](evaluation/footprint.md). `./setup.sh
  --uninstall --yes` deleted the Colima virtual machine, the Python
  environment with Qt and the buildx link, and removed Homebrew with its own
  uninstaller and the 55 packages installed with it, the experimental QEMU
  among them, in 22 s. It left `~/.docker`, which was not empty, and named
  the Command Line Tools and the developer directory as left in place;
  Homebrew's uninstaller left `/opt/homebrew/etc`. `./setup.sh --yes` then
  installed everything again in 4.4 min, and all 124 checks came out as
  before. One thing stayed that should have gone: Homebrew's trust in the
  experimental tap, which the script took to go with Homebrew. The script
  now takes it back before it removes Homebrew. That change was run with
  stand-ins only: a copy of the script that cannot remove Homebrew, a record
  made for the test and a copy of the trust file. Where Homebrew went, the
  trust was gone and the record empty; where it could not be removed, the
  trust was given again and the record kept both entries; the script as it
  was left the trust in the same test. On this Mac the trust that had stayed
  was taken back by hand, with the experimental QEMU, and the build that
  followed has it in its record again.
- Linux: in containers, on a Linux host (x86-64) and on the Mac; for the
  Linux host itself see the item after this one. That host's own setup
  predates the record, so there was nothing for the script to remove on it. With apt in Ubuntu 24.04, as a user who gets root through
  `sudo`, the script installed some 300 packages and recorded each. The
  uninstall then ran with packages in place that the script did not install:
  unused dependencies from before setup, and a package installed after setup
  that needs `python3`. It left all of those, held `python3` back while that
  package needed it, and removed the rest; run again once that package was
  gone, it removed `python3` too and deleted the record. Of the packages that
  came with the script's own, a few stay that packages from before recommend
  (apt keeps those). The same run took the user out of the `kvm` and `docker`
  groups again, which setup had added them to, and disabled the Docker
  service that setup had enabled; the service was a stand-in, as a container
  has no systemd.
- Linux: on 2026-11-17 the setup was removed from the Linux host and
  installed again, for the
  [disk space and time values](evaluation/footprint.md). The record listed
  the Python environment with Qt only, which `./setup.sh --uninstall --yes`
  removed in 0.2 s; QEMU and the ARM build emulation, 32 packages, were
  removed by hand with `apt-get remove`, by name. Docker, which was on the
  host before, stayed. `./setup.sh --yes` installed all of it again in
  1.4 min, the packages, their versions and their marks were as before, and
  all 124 checks came out as before. The record lists the 32 packages now.
  Measured again on 2026-11-18 and 19, after the project was renamed, on
  the host without an installation and without a record under the new
  name: `./setup.sh --yes --arm-targets` installed the same 32 packages and
  the Python environment in 1.2 min and recorded them; of the 140 checks
  one more failed than before, `stb-start-container`, which passed five
  times out of six when run again.
  Running it showed a fault, now corrected: with the emulators gone,
  `./setup.sh --check` still took the ARM build emulation for present,
  because Docker's builder went on listing ARM among its platforms. Where
  the engine runs on the host's own kernel the script now asks the kernel.
- With dnf in Fedora, zypper in openSUSE Tumbleweed and pacman in Arch Linux
  the script installed its own packages, as root, and removed them again:
  all of them on openSUSE and Arch. On Fedora `systemd` and `systemd-udev`
  stay with what they need where they came with setup, because dnf protects
  them and removes nothing at all when asked for one of them; a Fedora host
  has them before setup. In all four, no package from before setup went.
  Podman's storage could not be reset inside a container; the script says so
  and goes on.
- Windows: run on the Windows host (x86-64) for what can go without taking
  the host's setup down. That setup predates the record, so the record began
  empty. Setup registered the ARM build emulation and recorded it;
  `setup.cmd -Uninstall` listed it, asked, removed the registration and
  deleted the record with its directory; setup then registered it again. This
  was run in Windows PowerShell 5.1, which `setup.cmd` uses, and setup also in
  PowerShell 7. With a record written for the purpose the uninstall removed
  the emulation's container image from the engine and settled entries whose
  package or machine was gone already, and its listing (`-Check`) told the
  host's real winget packages and Podman machine from ones that do not exist.
  Running it showed a fault, now corrected: where there was no answer to the
  question (`setup.cmd -Uninstall < NUL`), the script went on as if the
  answer were yes. No answer is a no now, also for the installation.
  Not run on Windows: removing a winget package. That passed only with
  stand-ins for winget, Podman and WSL, in PowerShell 7 on Linux.
- Windows: on 2026-11-16 the setup was removed from that host and installed
  again, for the [disk space and time values](evaluation/footprint.md).
  `setup.cmd -Uninstall -Yes` removed what the record had, in 11.7 s: the
  ARM build emulation with its image, the Podman machine and the Python
  environment with Qt. `podman machine rm` ended with an error there (status
  125, over a socket file it could not delete); the machine was gone all the
  same, and the script went on and deleted the record. The record did not
  list QEMU and Podman, which were on the host before it was kept: those
  were removed by hand (`winget uninstall`). Left behind: the download that
  Podman keeps of its machine image (249 MB in
  `~\.local\share\containers`), and four programs in
  `C:\Program Files\qemu` that QEMU's own uninstaller leaves. `setup.cmd
  -Yes` then installed everything again in 3.2 min, with two elevation
  prompts to answer, and its record lists QEMU and Podman now. Of the 124
  checks, 122 came out as before the removal. The web page check on the
  ARM32 target failed once and passed in two runs after it; the video on
  demand check on the ARM64 target, which had failed before, passed in
  three runs out of three.

### Linux

`setup.sh` installs with the distribution's package manager (apt, dnf, pacman
or zypper) and asks for root through `sudo`. As a host it has been run on
Kubuntu 24.04 only; the package installation of the other three has been run
in containers (Fedora, openSUSE Tumbleweed, Arch Linux).

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

    ./emu
    ./emu run [--mode container|vm] [--arch native|arm32|arm64] [--workload NAME]
              [--cpus N] [--memory MIB] [--resolution 720p|1080p|4k] [--graphics auto|host|emulated]
              [--window] [--fullscreen]
              [--redrat-profile ID] [--redrat-device ID]
              [--driver FEATURE=STRATEGY] [--option KEY=VALUE] [--screenshot DIR]
              [--mute] [--record] [--repeat N] [-- WORKLOAD_ARGS]

Started without any arguments, the launcher shows a settings window: a field
for every argument of `emu run` (the mode, the VM guest CPU, the workload, the
window mode, the options and the rest), the command line those settings make,
and a Start button. Start runs the emulator as that command line would, in
the terminal the launcher was started from; closing the window starts
nothing. The fields are made from the launcher's own argument list, so a new
argument has a field without further work. Where no window can be shown (Qt
is not installed), the launcher prints its usage, as it did before.

| Mode | What runs |
|---|---|
| `--mode container` | the target OS userland on the container runtime, for quick development and CI |
| `--mode vm` | the target OS kernel and userland in a QEMU virtual machine |
| `--mode vm --arch native` | the host's own CPU architecture on the host's hypervisor |
| `--mode vm --arch arm64` | a simulated 64-bit ARM target CPU (Cortex-A53); needs a host set up with `--arm-targets` |
| `--mode vm --arch arm32` | a simulated 32-bit ARM target CPU (Cortex-A15); needs a host set up with `--arm-targets` |

`--arch x86_64` also exists, to try the x86-64 image under emulation on an
ARM host. It is a diagnostic and not part of the test matrix. On the macOS
host its image (`./emu build --mode vm --arch x86_64`) built in 6.7 min and
the guest booted to the prompt in 8 s (2026-11-17, `./emu verify vm-x86_64`).
The image takes 1.86 GB, and its build added 11.4 GB to the container
engine's disk there, which does not shrink again
([disk space and times](evaluation/footprint.md)).

Workloads: `prompt` (interactive shell), `bench` (CPU, memory and I/O
benchmarks), `driver-check`, `graphics-demo`, `media-decode`, `web-bench`
(the WPE WebKit browser), `remote-keys` (shows the remote control keys that
arrive) and `stb-simulator` (a set-top-box user interface with channels, an
app launcher and video on demand; see [STB simulator](#stb-simulator)). `./emu workloads` lists them.

Other commands: `./emu build`, `./emu config redrat`, `./emu doctor`,
`./emu matrix`, `./emu workloads`, `./emu verify`, `./emu report`,
`./emu audio`. Each has `--help`.

## Target OS image

[target/Dockerfile](target/Dockerfile) defines the simulated target OS once,
on Debian 13. The container runtime builds it either as a container image or
as VM artifacts (ext4 root filesystem, Debian kernel, initramfs), for x86-64,
ARM64 and ARM32. [target/image.json](target/image.json) pins its source: the
base image digest and a dated Debian package snapshot.

A build tidies the container engine after itself. It removes the images of
other versions of the definition, the images that a build of the same
version took the tag from (the launcher labels what it builds, `emu.image`,
to know them), and build steps that no build has used for 48 hours, and it
says what went. The last of these is the engine's whole build cache, other
projects' included; images that are not this project's are never touched.
`./emu build --keep-old` leaves everything in place. The images of the
current version and their build steps stay, about 25 GB for four targets
on Linux ([disk space and times](evaluation/footprint.md)). Run on the
Linux host with Docker; not run with Podman or on macOS yet, where the
engine's disk file does not shrink when its contents go.

[target/rootfs/opt/emu/init](target/rootfs/opt/emu/init) is the target's init
in both modes: PID 1 in a VM, the entrypoint in a container. It brings up the
environment, starts the driver-feature providers and runs one workload.

For graphics the image carries the Weston Wayland compositor, Mesa's OpenGL ES
and Vulkan drivers, and a Flutter application built with a pinned Flutter SDK.
For media it carries FFmpeg's decoders with the `ffmpeg` program, the mpv
player and ALSA as the audio interface. For the web it carries the WPE WebKit
browser engine with Cog, its launcher, and the GStreamer plugins WebKit plays
media with. These are choices for the evaluation image, not statements about
the real target's middleware.

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
`--graphics`, `--window` or `--fullscreen` is given.
`--resolution` selects 720p, 1080p (the default) or 4K.

| | VM mode | Container mode |
|---|---|---|
| Display | QEMU's emulated display adapter, driven by the target kernel's DRM/KMS driver | none; the compositor renders to a headless output of the selected size |
| `--window` | the display is shown in the launcher's window, which gets it from QEMU | the same window; a program in the target serves the display to it |
| `--graphics emulated` | the target CPU renders OpenGL ES and Vulkan (Mesa llvmpipe and lavapipe) | the same |
| `--graphics host` | QEMU's virtio-gpu maps OpenGL ES, and Vulkan where QEMU offers it, to the host GPU | the container gets the engine's GPU render node (`/dev/dri`) |

`--graphics auto`, the default, uses host acceleration when the host has a
compatible one and otherwise emulates; the launcher prints which it chose and
why. `--graphics host` fails rather than silently emulating.

Without a window the display is not shown anywhere; `--screenshot` captures
it. [Display window](#display-window) below describes the window.

What the verified hosts offer; `./emu doctor` shows it for any host:

- macOS on ARM64, with the QEMU that `setup.sh` installs: no host
  acceleration, in either mode. Homebrew's QEMU is built without the
  GPU-accelerated display device, and QEMU itself has no OpenGL display for
  macOS. The container engine's virtual machine has no GPU. `--window` shows
  the emulated display in the launcher's window, and such a display can be
  captured.
- macOS on ARM64, with an experimental QEMU build: host acceleration in VM
  mode with `--window`, in QEMU's own window. See
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
- Windows on x86-64, VM mode with `--window`: host acceleration, in QEMU's
  own window. QEMU 11.1.0
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

### Display window

`--window` shows the emulator's display in a window of the launcher's own,
in both modes; `--fullscreen` starts it full screen. Closing the window ends
the emulator.

- **Toolbar** (windowed only): mute, 1:1, full screen, and the on-screen
  remote control. Mute switches the run's audio as `./emu audio mute` does;
  it is off for a run that plays no sound through the host.
- **Scaling.** The display is scaled to the window and keeps its shape. The
  window opens at 1:1, one pixel of the display on one pixel of the screen, or
  as large as the screen allows. The 1:1 button returns to that.
- **Hotkeys.** Ctrl+Alt+F or F11 switches between the window and full screen;
  Ctrl+Alt+M mutes, Ctrl+Alt+1 is 1:1, Ctrl+Alt+R shows or hides the remote.
  On a Mac use Control or Command with Option. The on-screen remote starts
  hidden; the toolbar button or Ctrl+Alt+R toggles it.
- **How the display gets there.** In VM mode QEMU serves it (its VNC server,
  on a socket of the run, or on a loopback port on Windows). In container mode
  a program in the target captures the compositor's output and serves it the
  same way on a port published on the host's loopback address
  ([target/src/emuscreen.c](target/src/emuscreen.c)). That is done only
  while a window is open, and it is not free: see the limits below.
- **QEMU's own window.** Where QEMU can show a display that is rendered on
  the host GPU only in a window of its own (the experimental QEMU on macOS,
  and QEMU on Windows), and host acceleration is asked for or preferred, the
  display is shown there, as before: without toolbar, scaling control or
  remote control keys. `--graphics emulated` gets the launcher's window, and
  so does `--window`, `--fullscreen`, or a workload that is operated with
  remote control keys (`stb-simulator`), while host acceleration is only
  preferred (`--graphics auto`, the default): the keys come before the
  acceleration, and the launcher says so. `--option window=qemu` gets QEMU's.

Limits:

- Run on the macOS and Windows hosts, with emulated graphics, in all four
  modes at 720p, and at 4K in a host-native VM (on Windows in container mode
  as well). Run on the Linux host too (X11, KDE Plasma), in all four modes
  at 720p; there a VM's display is rendered on the host GPU and still shown
  in the launcher's window.
- On Windows, QEMU shows a display rendered on the host GPU only in its own
  window, so `--mode vm --window --graphics host` gets that window there,
  without toolbar or keys; use `--graphics emulated` for the launcher's.
- In VM mode the launcher's window reads the display from QEMU's VNC server,
  which in QEMU 8.2 (the Linux host's) serves no more than 2560x2048 pixels.
  Of a 4K display the window then shows the top left part, with host and
  with emulated graphics alike, and the launcher says so. `--option
  window=qemu` shows the whole 4K display there, rendered on the host GPU, in
  QEMU's own window. QEMU 11 (macOS, Windows) serves all of it.
- Full screen is the window system's: on macOS it worked when the system had
  made the window the active application, and a window that was started from
  a background session and not made active reported full screen without
  growing.
- Pixels travel unpacked. That is fine on one machine; a container engine
  inside a virtual machine (macOS, Windows) carries them over its network
  path. Measured on the macOS host at 1080p
  ([procedures](evaluation/procedures.md#timings-of-the-simulator)): in
  container mode a video of 25 frames a second reached the window whole
  (24.6 to 24.8 pictures a second), and a change on a quiet screen after
  0.08 s.
- In VM mode the window gets less of a video, and a quiet screen's change
  later: QEMU's display server sends a picture when the window has asked for
  one and its own clock comes round, and it slows that clock down while the
  display does not change. On the macOS host a host-native VM's window got 14
  to 17 pictures a second of such a video, and showed a change on a quiet
  screen after 0.12 s, or after 0.5 to 0.7 s (0.2 to 0.9 s) when the screen
  had shown nothing new for 5 seconds or more. That QEMU's clock is the cause is read
  from how QEMU is built, not shown by a test. The Linux and Windows hosts
  have not been measured.
- The window costs the target's graphics some speed, so results for the
  evaluation are taken without it. On the macOS host at 1080p, the graphics
  workload with the window against the same image without it: plain Wayland
  drawing 25% lower in container mode and 37 to 38% lower on the simulated
  ARM targets (1% in a host-native VM); OpenGL ES 3 to 10% lower; Vulkan 9%
  lower in container mode, 12% in a host-native VM and 17% on the ARM64
  target. The browser's drawing was 13% lower in container mode and 18% in a
  host-native VM.
- With the window, the media workload stalled in 3 of 10 runs in the ARM64
  VM on the macOS host: a playback froze within seconds of its start and the
  run had to be ended. Without the window the same runs completed. The cause
  is not known ([known issues](evaluation/results/known-issues.json)).
- macOS slows down a program whose window cannot be seen: one in the
  background, or any while the screen is locked (App Nap). A VM's window
  then got about 5 pictures a second of a video where it had got about 15,
  within two minutes of its start. The window now tells macOS that it shows
  a live picture, which keeps its pace; it does not keep the display or the
  Mac awake. All of these measurements were taken unattended, with the Mac's
  screen locked; how the window does in front of a user was not measured.

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

Three things can stop the option:

- The tap's history is a single commit. If the tap is rewritten, that commit
  may no longer be there to fetch; the option then stops and says so.
- Homebrew's own `virglrenderer` has the same name as the tap's. Where that
  one is installed, the option stops and does not replace it.
- The sources are forks whose branches their author rewrites, while Homebrew
  clones a source's branches and looks for the commit among them. Since
  2026-11-16 the commits above of virglrenderer and of QEMU are on no branch
  any more. The servers still give them out by their ids, and a commit that
  no branch holds may be gone from a server one day; the option then stops
  and says so.

Where a commit is on no branch, the option asks the server for it by its id,
into Homebrew's clone of the source, and builds that part once more. In the
output the build of such a part first ends with `fatal: unable to read tree`,
and the lines after that say what the script does. This was run on
2026-11-16 on the Mac after the build, the packages that came with it, the
tap and Homebrew's downloads had been removed: one run of the option built
all five parts, in 6.8 min, from the commits above.

`./setup.sh --uninstall` removes the build with everything else the script
installed (see [Removing what setup installed](#removing-what-setup-installed)).
To remove only the build (Homebrew does not uninstall a pinned package):

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
- This build maps OpenGL ES only: the target gets no desktop OpenGL context.
  GTK asks for one and does not go on to OpenGL ES by itself, so the Flutter
  application first drew nothing there: its window stayed black, while the
  test reported 60 frames/s for frames that were never shown. The target's
  display service now tells GTK to use OpenGL ES where the display gives no
  desktop OpenGL (`emugfx desktop-gl` says which), and the Flutter test
  reports itself unavailable when its window is not shown. With that, the
  target's own screenshot shows the Flutter frame full screen, and so does
  the QEMU window, which was looked at by eye.
- Frames per second at 1080p, host graphics against emulated:

  | Test | Host-native | ARM64 | ARM32 |
  |---|---|---|---|
  | OpenGL ES | 87 to 100 against 143 | 205 against 2.8 | 104 against 1.5 |
  | Flutter | 60 against 17 | 28 against 0.5 | no Flutter |

  On a host-native target the OpenGL ES test stayed at about 100 frames/s at
  every resolution in one session, and gave 87 and 90 in two later runs at
  1080p. At 4K, 100 is against 35 emulated, and Flutter is at 58 against 5.
  The Flutter numbers are from after the change above.
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

## Remote control input

The emulator joins its remote-control inputs: mapped host keyboard keys work
whenever the launcher's display window has focus; the on-screen remote is an
optional window that starts hidden; and selecting a RedRat profile adds IR
input. These sources all deliver the same target key codes. The on-screen
remote is toggled by its toolbar icon or Ctrl+Alt+R (Command+Option+R on macOS).
RedRat signals are delivered only while the launcher's display window is
focused. A QEMU-owned display window has no launcher toolbar or keyboard input.

The keys are HbbTV's list of
buttons (ETSI TS 102 796 V1.7.1, Table 12):

| Remote control key | HbbTV key event | Host key | Linux key code | Symbol in the target |
|---|---|---|---|---|
| Up | VK_UP | `Up` | 103 | `Up` |
| Down | VK_DOWN | `Down` | 108 | `Down` |
| Left | VK_LEFT | `Left` | 105 | `Left` |
| Right | VK_RIGHT | `Right` | 106 | `Right` |
| OK | VK_ENTER | `Return`, `Enter` | 28 | `Return` |
| BACK | VK_BACK | `Backspace` | 158 | `XF86Back` |
| 0 | VK_0 | `0` | 11 | `0` |
| 1 | VK_1 | `1` | 2 | `1` |
| 2 | VK_2 | `2` | 3 | `2` |
| 3 | VK_3 | `3` | 4 | `3` |
| 4 | VK_4 | `4` | 5 | `4` |
| 5 | VK_5 | `5` | 6 | `5` |
| 6 | VK_6 | `6` | 7 | `6` |
| 7 | VK_7 | `7` | 8 | `7` |
| 8 | VK_8 | `8` | 9 | `8` |
| 9 | VK_9 | `9` | 10 | `9` |
| Red | VK_RED | `R` | 398 | `XF86Red` |
| Green | VK_GREEN | `G` | 399 | `XF86Green` |
| Yellow | VK_YELLOW | `Y` | 400 | `XF86Yellow` |
| Blue | VK_BLUE | `B` | 401 | `XF86Blue` |
| Play | VK_PLAY | `P` | 207 | `XF86AudioPlay` |
| Pause | VK_PAUSE | `U` | 201 | `XF86AudioPause` |
| Play/pause | VK_PLAY_PAUSE | `Space` | 164 | `XF86AudioPlay` |
| Stop | VK_STOP | `S` | 166 | `XF86AudioStop` |
| Fast forward | VK_FAST_FWD | `F` | 208 | `XF86AudioForward` |
| Rewind | VK_REWIND | `W` | 168 | `XF86AudioRewind` |
| Record | VK_RECORD | `C` | 167 | `XF86AudioRecord` |
| TEXT | none: handled by the terminal | `T` | 388 | none |
| P+ | none: handled by the terminal | `PageUp` | 402 | `XF86ChannelUp` |
| P- | none: handled by the terminal | `PageDown` | 403 | `XF86ChannelDown` |
| WEBTV | none: handled by the terminal | `H` | 150 | `XF86WWW` |
| EXIT | none: handled by the terminal | `Escape` | 174 | `XF86Close` |

The last column is what the target's keymap calls the key, as a program in
the target saw it. TEXT has a key code and no symbol. Play and play/pause have
different key codes and the same symbol.

    ./emu run --workload remote-keys

The `remote-keys` workload shows a still picture on the display and prints
every key that arrives, with its code and symbol.

### Learning and selecting a RedRat remote

    ./emu config redrat
    ./emu config redrat --device pico-id
    ./emu run --workload stb-simulator --redrat-profile living-room
    ./emu run --workload remote-keys --redrat-profile living-room

RedRat is off unless `--redrat-profile` is supplied. In the settings window,
the **Create new profile...** button next to the profile selector opens guided
learning. It saves and selects the profile without starting the emulator.
The profile dropdown reloads saved profiles whenever it is opened, without
requiring a restart of the settings window.
`emu config redrat` runs the same profile-creation task on its own; use
`--device ID` to override the automatic choice of the first detected receiver.
The settings window shows that automatic receiver in the empty receiver field.
Selecting a profile adds IR input alongside the keyboard and on-screen remote. The repository
starts with no learned remotes. Guided learning asks for a display name and a
unique lowercase, hyphen-separated id. Click **Start learning**, then press each
requested button twice, releasing it between presses. This learns signal variants
such as toggle bits. Each capture is checked with the same SDK timing and toggle
rules used during playback, not just compared as raw JSON. Conflicting captures
are rejected immediately, with the conflicting keys named; release the buttons
and retry, relearn the previous key, or skip the key. Saving checks the complete
learned mapping again. Decoder construction keeps distinct short/long pulse
variants separate without changing playback's normal timing-jitter tolerance.
Use **Skip key** when your remote has no physical button for a requested key.
Skipping discards any partial capture for that key. Skipped keys remain
available through the virtual remote and mapped keyboard keys. Save becomes
available after all keys have been learned or skipped; **Relearn previous key**
also lets you return to a skipped key. Cancel saves nothing; an existing profile
is never overwritten.

Profiles are portable JSON files in [`remotes/`](remotes), one per remote,
and can be committed and shared. Each contains a version, id, name, and a
`buttons` map from the key ids in [`emulator/remote.py`](emulator/remote.py)
to learned SDK signals; skipped keys are omitted from this map. One profile
is selected per run. Learning is local;
the emulator does not transmit IR or change the receiver's firmware.

`emu doctor` reports detected receivers. The first detected receiver is used
unless overridden with `--redrat-device ID`. The settings window refreshes
receiver detection while open. Selecting a RedRat profile without a receiver fails before building or
starting a target. The SDK helper owns the host USB device: no
USB passthrough to Docker or QEMU is needed, including for ARM guests.
The launcher also checks a selected profile with the SDK before building or
starting a target, so older ambiguous profiles fail before a VM is started.

IR repeats keep a key down and the target compositor supplies key repetition.
After 250 ms without a matching frame, on loss of window focus, or on receiver
shutdown, a held key is released. Unrecognized signals are reported in the
window's status bar. Receiver failures are reported and end the run instead
of silently falling back to another remote profile.

Linux USB access is granted to the active desktop user by
`70-tv-emu-redrat.rules`. Setup reloads and applies this rule to connected
receivers without a reboot; reconnect the device after setup if it is still
inaccessible. An SSH-only user may need a host-administrator-managed USB
permission policy. Windows uses the vendor's x86/x64 driver; it does not
provide an ARM64 driver. RedRat's SDK provides the shared host implementation
for Linux, macOS and Windows; testing on one host is not evidence that the
others have been verified.

`./emu verify redrat-support redrat-device` runs the software checks and an
actual receiver open/close check. Neither claims that physical remote keys
were received. To check those, learn a profile, run `remote-keys` in each
target mode, and verify its press/release reports while pressing buttons,
holding them, switching window focus and unplugging the receiver.

How the keys travel: the target's compositor gets a keyboard of its own, the
"remote control" ([target/src/emu_remote.c](target/src/emu_remote.c), a Weston
module), and the launcher's window tells it which keys to press and release:
through a program it runs in the container, or, in VM mode, down a connection
the target opens to the window. An emulated PC keyboard or a VNC connection
could not carry them: the colour keys, say, have key codes that no PC
keyboard sends. The compositor gets that keyboard only when remote control
input is on, so runs without a window are as they were.

Limits:

- Verified on the macOS and Windows hosts, in all four modes: each of the 32
  keys by its host key and by its button. Verified on the Linux host as well.
- These keyboard/button results are not physical IR results. Real IR learning,
  decoding, held buttons and focus transitions must also be checked with a
  remote pointed at the attached receiver; no learned profiles are fabricated.
- That host keys stay away from the target while another window has the focus
  follows from how windows get keys. The checks do not cover it; it was tried
  by hand on Windows, in container and host-native VM modes, with key presses
  given to Windows itself: they reached the target while the emulator's
  window had the focus and not while another had it.
- A key reaches the target as a key code. Turning the codes into HbbTV's key
  events is the job of an HbbTV application's browser; the image's browser is
  not one, and what it makes of each key was not looked at.
- The module uses three functions that Weston exports for its own backends
  and does not declare in the headers it installs. They are declared in the
  module as Weston 14 has them, the version the image pins.

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
| `host` (the default) | QEMU's emulated sound card (virtio-sound) with the target kernel's driver; the card's backend hands the samples to the launcher's host-side audio process. If QEMU has no virtio-sound device, an ALSA shim sends them through QEMU's network instead. | a shim ALSA device ([target/src/emu_alsa.c](target/src/emu_alsa.c)) sends the samples to that process over TCP |
| `emulated` | the same sound card with no backend: the kernel's driver plays to nowhere. If QEMU has no virtio-sound device, a software model plays to nowhere at the sample rate. | a software model of a sound card: the same ALSA device, playing to nowhere at the sample rate |
| `mocked` | no sound card; a stub ALSA device discards the samples | the same stub |

The host-side audio process plays the sound with a player program, so it
goes wherever the host's sound system sends an application's sound. On Linux
that is the host's own `pacat`, `pw-cat` or `aplay`, whichever is installed.
macOS has no such program, so the launcher builds one the first time it is
needed ([emulator/coreaudio_player.c](emulator/coreaudio_player.c), into
`build/host/`); it plays through a Core Audio queue. Windows has none either;
there the player is a module of the launcher
([emulator/winmm_player.py](emulator/winmm_player.py)) that plays through the
system's wave output and needs nothing but Python.
`--option audio-sink=NAME` chooses the host's output device, and
`--option audio-output=none` takes the sound in without playing it. On macOS
and Windows `--option audio-volume=0..100` sets the volume. The output
devices are listed by `build/host/emu-coreaudio devices` on macOS and by
`py -3 -m emulator.winmm_player devices` on Windows, where a device is named
by its number or its name.

On Windows the volume is the application's volume in the Windows mixer, which
Windows remembers for the program that set it: the Python interpreter. The
player puts back the volume it found when it ends, and one that was stopped
before it could leaves a note in `build/host/` from which the next one does.

Mute while it runs, from another terminal:

    ./emu audio mute | unmute | toggle | status

`./emu run --mute` starts muted. A muted emulator keeps playing: the target
notices nothing, and the host gets silence in place of the sound.

Limits:

- On macOS and Windows the checks play at volume 0 and record what the
  system's audio output takes for the device; nobody has listened to it on
  either yet.
- In VM mode QEMU writes the sound card's output into a named pipe: a FIFO in
  the run's directory on Linux and macOS, a pipe in Windows' own pipe
  namespace (`\\.\pipe\emu-audio-...`) on Windows. A host with neither
  would fall back to the container mode's shim device over QEMU's network;
  that path has not been run.
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
- The dropped-frame values are the players' own counts. Compared with the
  display's own record on the macOS host, they hold to within three frames,
  except through OpenGL ES on a simulated ARM32 target: there mpv counts six
  to eleven more frames as shown than the display shows
  ([procedures](evaluation/procedures.md#audio-and-video-decoding)).
- mpv's OpenGL ES and Vulkan outputs use its plain rendering path
  (`--gpu-dumb-mode`). With its default path, Mesa's CPU renderer showed a
  black or green picture in many runs.

## Web browser

The image has WPE WebKit (Debian's 2.48, with Cog 0.18 as its launcher). The
`web-bench` workload starts it as a Wayland client, full screen on the
target's display, on pages of its own
([target/rootfs/opt/emu/web](target/rootfs/opt/emu/web)) that it serves over
the target's loopback interface:

| Test | What it does |
|---|---|
| `launch` | the browser starts, loads a page and runs its script |
| `render` | a fixed animated page for a fixed time: frames per second |
| `mse` | the fragmented reference streams (MPEG-2, AVC, HEVC) played through Media Source Extensions, with sound: frames that did not reach the display |

    ./emu run --mode vm --workload web-bench --window          # the three tests, with the display in a window
    ./emu run --workload web-bench -- --tests launch            # only start the browser
    ./emu run --workload web-bench -- --tests mse --streams avc-fragments

- WebKit's process sandbox is off in the target: it needs kernel features a
  container does not give. The browser loads only the workload's own pages.
- WebKit starts media with sound only after a click, unless its embedder
  allows a page more, and Cog has no option for that. The workload loads a
  small library into Cog that gives its pages that permission
  ([target/src/emu_web_autoplay.c](target/src/emu_web_autoplay.c)).
- Graphics are the display's: with emulated graphics the browser draws with
  Mesa's CPU renderer, like every other OpenGL ES program in the target.
- MSE playback counts a frame as shown only if it reached the display. The
  browser counts frames at its video output, and the target's compositor
  records how often it showed something new; the smaller count is taken. On a
  simulated ARM target the browser counts every frame of a stream while the
  display shows a handful
  ([procedures](evaluation/procedures.md#web)).

## STB simulator

    ./emu run --workload stb-simulator                         # in a window, keys from the keyboard
    ./emu run --mode vm --workload stb-simulator                           # toggle the on-screen remote as needed

The `stb-simulator` workload shows a set-top-box-like user interface on the
target's display and is operated with remote control keys alone
([Remote control input](#remote-control-input)). It gets the launcher's
window without being asked, since it is used through its display. The user
interface is a web application
([target/rootfs/opt/emu/stb](target/rootfs/opt/emu/stb)) shown full screen by
the image's browser, WPE WebKit; the workload starts the browser, serves the
application and its media over the target's loopback interface, and does
what a page cannot.

| Screen | What it does |
|---|---|
| TV channels | the channel list. OK plays the selected channel, full screen, with its sound; Up and Down change the channel, a digit selects one by number, BACK returns to the list |
| Apps | the app launcher, with the video on demand application |
| Performance tests | starts a workload of the performance evaluation: `bench`, `graphics-demo`, `media-decode` or `web-bench` |
| Switch off | ends the simulator |

The arrow keys move the selection, OK opens what is selected, BACK returns
to where the user was, and EXIT goes to the home screen.

- **Channels** are the reference streams of the media workload, one per
  video codec (MPEG-2 with MP2, AVC with AAC, HEVC with AC-3), each played
  in a loop through Media Source Extensions. They need no network. The
  streams are five seconds long, so a channel repeats every five seconds.
- **Video on demand** is a web application of its own
  ([vod](target/rootfs/opt/emu/stb/vod)), started from the app launcher in
  the same browser; BACK or EXIT at its titles returns to the simulator. Its
  titles are MPEG-DASH streams, played with [dash.js](https://dashjs.org)
  (version 5.3.0, BSD 3-Clause), which chooses among a stream's
  representations as it plays, by the speed of the connection and no larger
  than the display. The titles ([titles.json](target/rootfs/opt/emu/stb/vod/titles.json))
  are the Blender open films, as DASH streams that others serve on the
  internet: Big Buck Bunny (Akamai's DASH test content), Elephants Dream
  (BBC Research & Development), Sintel and Tears of Steel (the Shaka Player
  demo assets). The target reaches them through the host's network; a title
  it cannot reach is refused with a message, and the application stays
  usable. Two more titles are a 20 second test stream that is on the device,
  in three sizes (240p, 480p, 720p; [build-abr.sh](target/media/build-abr.sh)):
  once as it is, and once over a path the simulator serves at 0.6 Mbit/s,
  which carries only the smallest size. A block at the top centre of its
  picture names the size that is playing.
- **Performance tests** run as they do when the launcher starts them, and
  print their results as their own result lines, each marked as launched
  from the simulator; the user interface shows them when the workload is
  done. A workload that uses the display takes it over while it runs: the
  user interface is stopped and comes back with the results, and there is no
  key that ends such a workload early. `--record` records the run as one of
  `stb-simulator`; results for the evaluation are recorded by running the
  workloads themselves.
- What the user interface does is printed as `EMU-STB` lines on the
  launcher's terminal: every screen, selection, channel, title and
  representation. The checks go by them.
- dash.js is not in this repository: the image build fetches the release
  that [target/image.json](target/image.json) names from the npm registry and
  checks its SHA-256. The image also has the certificate authorities the
  browser needs for HTTPS.

How fast it is, timed on the macOS host at 1080p from the launcher's window
(medians; the method is in the
[procedures](evaluation/procedures.md#timings-of-the-simulator), every value
with its spread in
[evaluation/stb-timings/macos-arm64.md](evaluation/stb-timings/macos-arm64.md)).
These are findings, not results of the evaluation:

| | Container | VM, host-native | VM, ARM64 | VM, ARM32 |
|---|---|---|---|---|
| Launch to the home screen | 0.93 s | 1.32 s | 11.8 s | 29.7 s |
| A key to the user interface's answer | 0.007 s | 0.005 s | 0.041 s | 0.046 s |
| A key to the changed picture in the window | 0.078 s | 0.12 s | 0.94 s | 1.16 s |
| The same after 30 s without a new picture | 0.15 s | 0.67 s | 1.84 s | 2.45 s |
| Channel change to the channel's picture in the window | 0.16 s | 0.28 s | 2.30 s | 3.03 s |
| Pictures a second of a channel in the window (the streams have 25) | 24.6 to 24.8 | 14.2 to 17.0 | 1.4 to 1.5 | 0.7 to 0.9 |
| Video on demand application started | 0.16 s | 0.17 s | 0.46 s | 0.40 s |
| Test title playing after OK | 0.13 s | 0.17 s | 1.44 s | 1.83 s |
| Big Buck Bunny shown at 1920x1080 after OK | 4.06 s | 4.40 s | 6.09 s | 5.83 s |
| User interface back after a workload that took the display | 0.16 s | 0.11 s | 2.50 s | 2.68 s |

A performance workload started from the performance tests screen reports
what it reports when the launcher runs it with the same window, with two
exceptions. The browser of `web-bench` starts in half to three quarters of
the time, since the simulator's browser ran just before it. And `bench` does
not take the display, so the simulator's browser stays up beside it: on the
simulated ARM targets 9 and 10 of its 13 results came out 11 to 35% lower
(natively its processor and memory tests agreed within 7%, and its storage
tests vary from run to run either way). Results for the
evaluation are recorded by running the workloads themselves, without a window
([Display window](#display-window) has what the window costs).

Limits:

- The browser does not tell a page about the P+, P-, TEXT and WEBTV keys
  (they arrive as keys without a name), so the channel is changed with Up
  and Down and with the digits, not with P+ and P-.
- Physical RedRat operation of the simulator still needs verification with a
  learned remote; keyboard and on-screen remote results do not establish it.
- With the CPU emulated (ARM64 and ARM32 targets) the browser draws far
  below real time: the user interface takes about a second to show what a
  key did, and a channel shows about one picture a second (the table above;
  [Web browser](#web-browser)).
- The films depend on servers that are not this project's; a stream that
  moves or goes away has to be replaced in `titles.json`.
- On the Windows host, video on demand fails in the ARM64 and ARM32 VMs when
  the player leaves a title's smallest representation: in the ARM64 VM the
  browser's renderer process ends (the simulator starts the browser again),
  in the ARM32 VM the title is refused or its picture stays at the smallest
  size. A title that stays at one representation plays. The channels, the
  user interface and the performance tests work there, and everything works
  in container mode and in the host-native VM. On Linux the same title
  stalled once in the ARM64 VM. The cause is not known.

The simulator is verified on Linux, on macOS and on Windows (there with the
exception above).

## Evaluation

- [evaluation/matrix.json](evaluation/matrix.json): the hosts and modes to cover.
- [evaluation/workloads.json](evaluation/workloads.json): the versioned workloads.
- [evaluation/procedures.md](evaluation/procedures.md): how measurements are made.
- `evaluation/results/`: recorded results (`./emu run ... --record`), and a
  page that shows them as charts (see below).
- `evaluation/verification/`: what `./emu verify` has confirmed, per host and
  machine (`HOST_MACHINE.json`; see "Machines" in the procedures).
- [evaluation/footprint.md](evaluation/footprint.md): the disk space of the
  host installation and of each target, and the install, build and run times
  that the report has to state. The macOS and the Linux host are measured,
  and the Windows host but for three build values that its disk had no room
  for.
  [evaluation/footprint.py](evaluation/footprint.py) adds up the run times
  from the recorded results and prints the sizes of a host's targets
  ([procedures](evaluation/procedures.md#disk-space-and-times)).
- [evaluation/stb-timings.py](evaluation/stb-timings.py) and
  `evaluation/stb-timings/`: how fast the STB simulator starts and answers,
  and what the performance workloads report when started from it, per host.
  Findings, not results of the evaluation
  ([procedures](evaluation/procedures.md#timings-of-the-simulator)).

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
dropped on it. A listed record that cannot be read is asked for again, and
the page says at its top if one is still missing: until 2026-11-16 such a
record was left out without a word, and the server reset a connection often
enough for that to happen (it now keeps its connections open).

The page starts with the hosts the results were measured on: CPU, memory,
GPU with its driver, operating system and emulator software, as the records
describe them. (Records made before the launcher recorded the GPU name it only
where a test rendered on it.) [machines.json](evaluation/results/machines.json)
adds what was stated about each machine, such as its GPU where the
records do not have it; the page marks that as stated.

A host on the page is a host OS on one machine. Every record names its
machine (`host.machine`, made from the CPU model, or the name in
`EMU_MACHINE`), so two machines with the same host OS are two hosts, each
named with its machine id, and their results are not put together. One
machine measured under two host operating systems is two hosts as well, and
the description of each says that the other is the same machine.

Under the hosts is "Platform support and known issues": a matrix with a row
for each feature the launcher's checks cover and, for each host, a cell per
emulator mode that says whether `./emu verify` verified it there, found it
failing, or could not run it on that host. It is made from the verification
reports in `evaluation/verification/` on each load, which the server hands
out as well, so it follows the last `./emu verify` of each host; pointing at
a cell shows what the check found. Below it are the known issues and limits,
with the hosts and modes each applies to: those that make a check fail, those
no check covers, and what is not implemented. That list is kept by hand, in
[known-issues.json](evaluation/results/known-issues.json); the task list has
the full account of each entry. Without the launcher's server, pick the
`evaluation` folder so that the page gets the verification reports too.

Each test has a card with one row per host and emulator mode. A bar is the
median of that configuration's runs and the dots are the single runs. The
hosts can be filtered, values can be shown relative to the container on the
same host, and pointing at a row shows the details of its runs.

At the end is "Disk space and times": for each host the disk space of the
host installation and of each target, and the install, build and performance
evaluation times, with how each value was taken. The page shows the tables of
[evaluation/footprint.md](evaluation/footprint.md) as they are, which the
server hands out as well, so a value that is not measured reads so there too.
What each value is, and what the measurements showed, is in that document
only. Without the launcher's server, the `evaluation` folder has it.

### Results as PDF

[emulator-results.pdf](evaluation/results/emulator-results.pdf) is a snapshot
of the page: the hosts, the support matrix with the known issues, the charts,
and the disk space and times. Unlike the page it does not follow new runs. To make it again,
start `./emu report` and either print the page from the browser (Save as PDF;
the page has its own print layout, A4 landscape, without the list of
records), or let Chrome
do it without a window:

    ./emu report --no-browser &
    google-chrome --headless=new --no-pdf-header-footer --virtual-time-budget=8000 \
        --print-to-pdf=evaluation/results/emulator-results.pdf http://127.0.0.1:8765/

`--virtual-time-budget` gives the page time to read the records before it is
printed. The PDF shows all hosts with measured values, the page's defaults.
Its first page says how many records it shows: that is to be the number of
record files in `evaluation/results/`.
This was run with Chrome on Linux, on Windows (there with `emu.cmd` and
Chrome's `chrome.exe`) and on macOS (there with
`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`). On macOS
a newly installed Chrome that had never been opened stopped at once with
"Failed to get the path for 1001"; after it had been opened once, the command
worked.

The snapshot in the repository was made on the Linux host on 2026-11-19,
with the CPU, graphics, media and browser results of all three hosts.
Windows' MSE playback values in it
are those measured again that day with version 1.1.0 of the workload; the
earlier ones are kept as records and not charted
([procedures](evaluation/procedures.md#web)).
