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
  - Open: the Wayland compositor is not stable in ARM32 VM mode. On Windows (x86-64) the compositor process ended, without a message in its log, in 2 of 12 runs of the graphics workload and once in 12 rounds of the Wayland and OpenGL ES tests inside one VM. The OpenGL ES test that follows then reports a lost connection, so the `gles-vm-arm32` check fails now and then; its recorded pass on Windows is from a run in which this did not happen. Whether it happens on macOS has not been tested; the check passed there. The cause is not investigated.
- [ ] 4.2 Prefer compatible host graphics acceleration and retain emulation fallback; verify both paths.
  - Implemented: `--graphics auto|host|emulated`. `auto` uses host acceleration when the host has a compatible one (QEMU's virtio-gpu with virglrenderer in VM mode, the container engine's GPU render node in container mode) and otherwise emulates.
  - Verified on macOS (ARM64), Windows (x86-64) and Linux (x86-64): emulation on request, and as the fallback of `auto`, in container and VM modes.
  - Verified on Linux (x86-64, QEMU 8.2.2, NVIDIA GPU with NVIDIA's driver) by `./emu verify`: host acceleration in VM mode without a window. `--graphics host` and `auto` both select it, the target reports OpenGL ES rendered on the host GPU, and the capture of the emulator's display shows the accelerated frame. This is the first host where the check `graphics-host-vm` passes. Flutter is accelerated too, and simulated ARM64 and ARM32 targets get it as well; Vulkan stays on the target CPU, because QEMU 8.2 does not map it.
  - Checked by hand on Linux: the same in QEMU's SDL window (`--window`), with host and with emulated graphics; QEMU ends cleanly there.
  - On Linux, host acceleration requires a GPU render node (`/dev/dri/renderD*`). Without one the host renders its own OpenGL on the CPU, and the launcher emulates instead; this was the state of the Linux host at its first verification, and the fallback of `auto` was verified then.
  - Open: host acceleration in container mode is not verified on any host. On the Linux host the engine has a render node, but it belongs to NVIDIA's driver, which the target's Mesa cannot render with; the launcher detects that and emulates. A Linux host whose GPU has a Mesa driver (Intel, AMD) is needed to run this path.
  - Open: the target reports OpenGL ES as accelerated when the host's OpenGL behind virtio-gpu is itself CPU-rendered (renderer `virgl (LLVMPIPE ...)`; the software-renderer test in `target/src/emugfx.c` is case-sensitive). The render-node requirement keeps the launcher from choosing that on Linux where no GPU driver is loaded. Fixing it changes the image definition, so every host has to rebuild and verify again.
  - macOS (ARM64) has none with the installed tools: Homebrew's QEMU is built without the GPU-accelerated display device, and the container engine's virtual machine has no GPU. In container mode on Windows, Podman's engine in WSL has no GPU render node.
  - Host acceleration works in VM mode on Windows when the display is shown in a window (`emu run --window`, QEMU 11.1.0, NVIDIA GPU), and `auto` prefers it there. Checked by hand, not by `./emu verify`: the target reported OpenGL ES and Flutter rendered on the host GPU (175 and 59 frames/s, against 99 and 17 emulated), pictures taken of the window showed those frames, and a simulated ARM64 target was accelerated as well. Vulkan stayed on the target CPU.
  - Open: QEMU ends with an access violation after the target has shut down whenever it showed a display rendered on the host GPU on Windows. The workload's results are complete by then; the launcher reports the status.
  - Open: on Windows there is no capture of a display that is rendered on the host GPU, so the verification of this path cannot be automated there. On Linux the capture from QEMU's VNC server works, but reaches no further than 2560x2048 pixels: of a 4K display it shows the top left part. The resolution checks compare that part, and confirm the whole 4K frame with emulated graphics. QEMU refuses to capture such a display over its machine protocol. Without a window the launcher reads the capture from QEMU's VNC server instead; that capture is confirmed against the emulated display, but on Windows QEMU's display without a window (`egl-headless`) stays black, which is why host acceleration is used there only with a window. With a window QEMU offers no capture at all.
- [x] 4.3 Support 720p, 1080p, and 4K rendering and verify each selected resolution.
  - Verified with emulated graphics in all four modes, on macOS (ARM64), on Windows (x86-64) and on Linux (x86-64), by capturing the emulator's display at each resolution. ARM32 VM mode is covered with Wayland and OpenGL ES only (see 4.1).

## 5. Stage 4: Media playback
- [ ] 5.1 Accept MP2TS, MP4, and MSE-style fragment input and verify each media input path.
- [ ] 5.2 Decode MPEG-2, AVC, and HEVC video and MP2, AC-3, AAC, and HE-AAC audio; verify each codec.
- [ ] 5.3 Render decoded video through the supported graphics technologies and route audio through the host OS path; verify runtime mute and unmute.

## 6. Stage 5: Browser evaluation
- [ ] 6.1 Include WPE WebKit in the Linux client OS image and verify it launches.
- [ ] 6.2 Run web-performance workloads in WPE WebKit, including MSE playback, and verify playback results are recorded.

## 7. Stage 6: Windowed display UX
- [ ] 7.1 Implement windowed and full-screen modes with a hotkey to switch between them and verify both transitions.
  - Started ahead of this stage: `emu run --window` shows a VM's display in QEMU's own window (run with QEMU's SDL window, on Windows and on Linux with X11). Full-screen mode, the hotkey and their verification are not done.
- [ ] 7.2 Scale the display when the window is resized and verify the compact toolbar can mute audio and restore 1:1 pixel density.

## 8. Stage 7: Full qualification and report
- [ ] 8.1 Run the complete supported host OS, host CPU architecture, emulator mode, and VM guest architecture matrix and verify all required performance areas are measured or marked unavailable.
- [ ] 8.2 Produce the Slidev comparison with pros, cons, and actual results for each evaluated combination; verify unavailable results are explicit and no estimates are presented as measurements.

## Verification status

Checked tasks were verified with `./emu verify` on three hosts so far: macOS on ARM64, Windows on x86-64 with Podman as the container runtime, and Linux on x86-64 (Kubuntu 24.04) with Docker. `evaluation/verification/` records each check per host, as passed, failed, or unavailable on that host. The hosts were verified at different revisions of the target image; each record names the image definition it ran. Run `./setup.sh` and `./emu verify` on an x86-64 Mac and on Ubuntu 22.04 and 26.04 to extend the coverage; tasks 2.1 and 2.2 stay open until then, and task 4.2 until host acceleration is verified in container mode as well (in VM mode it is, on Linux).
