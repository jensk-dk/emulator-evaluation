# Tasks

## 1. Stage 0: Evaluation foundation
- [x] 1.1 Define the supported host OS and CPU test matrix and verify it covers every declared host combination.
- [x] 1.2 Select or build the Linux client OS image, verify it boots in VM mode, and record its source or build revision.
- [x] 1.3 Define versioned evaluation workloads and measurement procedures and verify they cover all required performance areas.

## 2. Stage 1: Cross-platform runnable baseline
- [ ] 2.1 Implement the host setup script for Linux, macOS, and Windows and verify it checks for and installs missing host dependencies on each host.
  - Implemented for all three (`setup.sh`, `setup.ps1` with `setup.cmd`). Verified on macOS (ARM64), on Windows (x86-64) and on Linux (x86-64, Kubuntu 24.04). Ubuntu 22.04 and 26.04, which the host-platform spec names, and an x86-64 Mac are not yet run.
  - On Linux the script installed QEMU's ARM system emulators and `qemu-user-static` with apt and registered the ARM build emulation. Python, the x86-64 QEMU with its OpenGL modules, KVM access and Docker were present already, so installing those was not exercised; nor were the dnf, pacman and zypper paths.
  - On Windows the script installed QEMU and Podman with winget, created Podman's machine, and registered and re-registered the ARM build emulation. Python and the Windows Hypervisor Platform were present already, so installing those two was not exercised. With Docker Desktop installed as well, its engine did not answer on this host; the script then uses Podman.
- [ ] 2.2 Implement the startup launcher for Linux, macOS, and Windows and verify it can launch the selected target workload on each host.
  - Implemented for all three (`emu`, `emu.cmd`). Verified on macOS (ARM64), on Windows (x86-64, with Podman as the container runtime) and on Linux (x86-64, Kubuntu 24.04, with Docker 20.10 as the container runtime and KVM). Podman as the runtime on Linux is not verified. Docker Desktop as the runtime on Windows is not verified.
- [x] 2.3 Build the simulated target OS container image from a Dockerfile or equivalent and verify it starts the target OS environment and an interactive prompt.
- [x] 2.4 Boot the target OS in host-native VM mode and verify the interactive prompt runs.
- [x] 2.5 Run initial CPU, memory allocation/bandwidth, and I/O workloads and verify their results are recorded with environment identity.

## 3. Stage 2: VM CPU and driver fidelity
- [x] 3.1 Implement ARM32 and ARM64 VM guest modes and verify each starts the target OS workload.
- [x] 3.2 Implement emulated, mocked, and host-routed driver-feature strategies in container and VM modes and verify each strategy in both modes.

## 4. Stage 3: Graphics support
- [ ] 4.1 Support Wayland, Flutter, OpenGL ES, and Vulkan workloads and verify each with a graphics workload.
  - Implemented as the `graphics-demo` workload. Verified on macOS (ARM64), on Windows (x86-64) and on Linux (x86-64), with the same outcome on all three: Wayland and OpenGL ES in container, host-native VM, ARM64 VM and ARM32 VM modes; Vulkan and Flutter in container, host-native VM and ARM64 VM modes.
  - Open: Vulkan in ARM32 VM mode. With emulated graphics Vulkan is rendered by Mesa's CPU driver, which crashes on 32-bit ARM. With Debian 13's Mesa 25.0, which the image uses, Debian's own `vkcube` demo crashes too. With Mesa 26.1 from Debian backports `vkcube` runs, but this project's test still crashes inside the driver, although the Khronos validation layers find no fault in it.
  - Open: Flutter in ARM32 VM mode. The Flutter SDK builds Linux applications for x86-64 and ARM64 only, so the ARM32 image has no Flutter workload.
  - Open: the Wayland compositor is not stable in ARM32 VM mode. On Windows (x86-64) the compositor process ended, without a message in its log, in 2 of 12 runs of the graphics workload and once in 12 rounds of the Wayland and OpenGL ES tests inside one VM. The OpenGL ES test that follows then reports a lost connection, so the `gles-vm-arm32` check fails now and then; its recorded pass on Windows is from a run in which this did not happen. It happens on macOS too: in the media checks there the display service ended during two of the three playbacks through Wayland (see 5.3). The cause is not investigated.
- [ ] 4.2 Prefer compatible host graphics acceleration and retain emulation fallback; verify both paths.
  - Implemented: `--graphics auto|host|emulated`. `auto` uses host acceleration when the host has a compatible one (QEMU's virtio-gpu with virglrenderer in VM mode, the container engine's GPU render node in container mode) and otherwise emulates.
  - Verified on macOS (ARM64), Windows (x86-64) and Linux (x86-64): emulation on request, and as the fallback of `auto`, in container and VM modes.
  - Verified on Linux (x86-64, QEMU 8.2.2, NVIDIA GPU with NVIDIA's driver) by `./emu verify`: host acceleration in VM mode without a window. `--graphics host` and `auto` both select it, the target reports OpenGL ES rendered on the host GPU, and the capture of the emulator's display shows the accelerated frame. This is the first host where the check `graphics-host-vm` passes. Flutter is accelerated too, and simulated ARM64 and ARM32 targets get it as well; Vulkan stays on the target CPU, because QEMU 8.2 does not map it.
  - Checked by hand on Linux: the same in QEMU's SDL window (`--window`), with host and with emulated graphics; QEMU ends cleanly there.
  - On Linux, host acceleration requires a GPU render node (`/dev/dri/renderD*`). Without one the host renders its own OpenGL on the CPU, and the launcher emulates instead; this was the state of the Linux host at its first verification, and the fallback of `auto` was verified then.
  - Open: host acceleration in container mode is not verified on any host. On the Linux host the engine has a render node, but it belongs to NVIDIA's driver, which the target's Mesa cannot render with; the launcher detects that and emulates. A Linux host whose GPU has a Mesa driver (Intel, AMD) is needed to run this path.
  - Open: the target reports OpenGL ES as accelerated when the host's OpenGL behind virtio-gpu is itself CPU-rendered (renderer `virgl (LLVMPIPE ...)`; the software-renderer test in `target/src/emugfx.c` is case-sensitive). The render-node requirement keeps the launcher from choosing that on Linux where no GPU driver is loaded. Fixing it changes the image definition, so every host has to rebuild and verify again.
  - macOS (ARM64) has none: Homebrew's QEMU is built without the GPU-accelerated display device, and QEMU itself has no OpenGL display for macOS. The builds that have one are patched forks in third-party Homebrew taps; they are not installed, and whether they accelerate a Linux target is not established. The container engine's virtual machine has no GPU. So on macOS the checks `graphics-host-vm` and `graphics-host-container` cannot run, and this is the one place where macOS is behind Linux.
  - In container mode on Windows, Podman's engine in WSL has no GPU render node.
  - Host acceleration works in VM mode on Windows when the display is shown in a window (`emu run --window`, QEMU 11.1.0, NVIDIA GPU), and `auto` prefers it there. Checked by hand, not by `./emu verify`: the target reported OpenGL ES and Flutter rendered on the host GPU (175 and 59 frames/s, against 99 and 17 emulated), pictures taken of the window showed those frames, and a simulated ARM64 target was accelerated as well. Vulkan stayed on the target CPU.
  - Open: QEMU ends with an access violation after the target has shut down whenever it showed a display rendered on the host GPU on Windows. The workload's results are complete by then; the launcher reports the status.
  - Open: on Windows there is no capture of a display that is rendered on the host GPU, so the verification of this path cannot be automated there. On Linux the capture from QEMU's VNC server works, but reaches no further than 2560x2048 pixels: of a 4K display it shows the top left part. The resolution checks compare that part, and confirm the whole 4K frame with emulated graphics. QEMU refuses to capture such a display over its machine protocol. Without a window the launcher reads the capture from QEMU's VNC server instead; that capture is confirmed against the emulated display, but on Windows QEMU's display without a window (`egl-headless`) stays black, which is why host acceleration is used there only with a window. With a window QEMU offers no capture at all.
- [x] 4.3 Support 720p, 1080p, and 4K rendering and verify each selected resolution.
  - Verified with emulated graphics in all four modes, on macOS (ARM64), on Windows (x86-64) and on Linux (x86-64), by capturing the emulator's display at each resolution. ARM32 VM mode is covered with Wayland and OpenGL ES only (see 4.1).

## 5. Stage 4: Media playback
- [ ] 5.1 Accept MP2TS, MP4, and MSE-style fragment input and verify each media input path.
  - Implemented as the `media-decode` workload. Verified on Linux (x86-64) and on macOS (ARM64) in container, host-native VM, ARM64 VM and ARM32 VM modes: each video codec is decoded from MP2TS, from MP4, and from an initialisation segment and media fragments appended one after another to the running decoder; audio-only streams from MP2TS and from MP4. Not yet run on Windows.
  - "MSE-style" here is the way the media arrives, as appended fragments. The Media Source API itself comes with the browser in stage 5.
- [ ] 5.2 Decode MPEG-2, AVC, and HEVC video and MP2, AC-3, AAC, and HE-AAC audio; verify each codec.
  - Verified on Linux (x86-64) and on macOS (ARM64) in all four modes, with FFmpeg's software decoders: every frame of each video stream is decoded, and each audio codec, HE-AAC from MP4 and from MP2TS. Not yet run on Windows.
  - The HE-AAC reference tone is a file in the repository (`target/media/heaac-1100hz.aac`): Debian and Ubuntu ship no HE-AAC encoder. It was made once with the Fraunhofer FDK AAC encoder; `target/media/build-media.sh` says how.
- [ ] 5.3 Render decoded video through the supported graphics technologies and route audio through the host OS path; verify runtime mute and unmute.
  - Video, verified on Linux (x86-64) and on macOS (ARM64) by capturing the emulator's display during playback: through Wayland, OpenGL ES, Vulkan and Flutter in container, host-native VM and ARM64 VM modes; through Wayland and OpenGL ES in ARM32 VM mode. On macOS all of it is with emulated graphics.
  - On macOS, where the simulated ARM targets have no host graphics, they show only part of a 25 frames/s 720p stream: an ARM64 target drops about 95 of 125 frames through OpenGL ES and up to 8 through Wayland; an ARM32 target about 107 through OpenGL ES and 70 to 80 through Wayland. Container and host-native VM modes drop none through Wayland, OpenGL ES and Vulkan.
  - Open: Vulkan and Flutter video in ARM32 VM mode, for the reasons under 4.1 (Mesa's CPU Vulkan driver crashes on 32-bit ARM; no Flutter SDK for it).
  - Open: in ARM32 VM mode the Wayland compositor ended during playback (the instability noted under 4.1): on Linux in both runs made, during one to three of the six playbacks through Wayland and OpenGL ES; on macOS in the one run made, during two of them. The workload notices, starts the display again and plays the stream once more, and says so in the result; a stream whose second playback also loses the display is reported as not played. The cause is still not investigated.
  - Open: the Flutter application shows about a third of the frames of a 25 frames/s 720p stream, with emulated and with host graphics alike. It gets decoded frames from a separate decoder and turns each into an image; a Flutter application that shows video through a texture filled by a native plugin is not built.
  - Audio, verified on Linux (x86-64) in all four modes: the target's ALSA device plays through the launcher's host-side audio process and the host's player program. The check plays each codec's tone into a private output device of the host's sound server (PipeWire here) and finds each pitch in a recording of that device.
  - Audio, verified on macOS (ARM64) in all four modes: the same path, with a player the launcher builds itself, because macOS has no program that plays raw samples (`emulator/coreaudio_player.c`, a Core Audio queue). macOS has no private output device without installing an audio driver, so the check plays on the default output device at volume 0, finds each pitch in what the system's audio queue took for the device, and has the system's audio server confirm that the player is playing. That shows the host's audio output took the sound; it is not a recording of what left the device, and nobody has listened to it.
  - Mute and unmute while playing, verified on Linux and on macOS in container and host-native VM modes: `emu audio mute|unmute` (and `emu run --mute`); the recording on the host shows the tone, two seconds of silence, and the tone again.
  - The audio driver feature has the three strategies of task 3.2; emulated and mocked are verified in container and host-native VM modes, on Linux and on macOS.
  - Open: playing through the host OS is implemented for Linux hosts (the host's `pacat`, `pw-cat` or `aplay`) and macOS hosts (the launcher's own player). On Windows the host-side audio process runs without a player: the sound arrives and can be muted, but is not heard. In VM mode on Windows the sound cannot take the emulated sound card's path (it needs a named pipe) and falls back to the container mode's path over the emulator's network, which has not been run.
  - Open: sound from two target programs playing at the same time is not mixed.
  - Open: the mute switch is a command. The toolbar button of stage 6 is to use the same switch.

## 6. Stage 5: Browser evaluation
- [ ] 6.1 Include WPE WebKit in the Linux client OS image and verify it launches.
- [ ] 6.2 Run web-performance workloads in WPE WebKit, including MSE playback, and verify playback results are recorded.

## 7. Stage 6: Windowed display UX
- [ ] 7.1 Implement windowed and full-screen modes with a hotkey to switch between them and verify both transitions.
  - Started ahead of this stage: `emu run --window` shows a VM's display in QEMU's own window (run with QEMU's SDL window on Windows and on Linux with X11, and with its Cocoa window on macOS). Full-screen mode, the hotkey and their verification are not done.
- [ ] 7.2 Scale the display when the window is resized and verify the compact toolbar can mute audio and restore 1:1 pixel density.

## 8. Stage 7: Full qualification and report
- [ ] 8.1 Run the complete supported host OS, host CPU architecture, emulator mode, and VM guest architecture matrix and verify all required performance areas are measured or marked unavailable.
- [ ] 8.2 Produce the Slidev comparison with pros, cons, and actual results for each evaluated combination; verify unavailable results are explicit and no estimates are presented as measurements.

## Verification status

Checked tasks were verified with `./emu verify` on three hosts so far (stage 4 on the Linux and macOS hosts): macOS on ARM64, Windows on x86-64 with Podman as the container runtime, and Linux on x86-64 (Kubuntu 24.04) with Docker. `evaluation/verification/` records each check per host, as passed, failed, or unavailable on that host. The hosts were verified at different revisions of the target image; each record names the image definition it ran. Run `./setup.sh` and `./emu verify` on an x86-64 Mac and on Ubuntu 22.04 and 26.04 to extend the coverage; tasks 2.1 and 2.2 stay open until then, tasks 5.1 to 5.3 until the Windows host has run them and plays sound, and task 4.2 until host acceleration is verified in container mode as well (in VM mode it is, on Linux).
