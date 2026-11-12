# Tasks

## 1. Stage 0: Evaluation foundation
- [x] 1.1 Define the supported host OS and CPU test matrix and verify it covers every declared host combination.
- [x] 1.2 Select or build the Linux client OS image, verify it boots in VM mode, and record its source or build revision.
- [x] 1.3 Define versioned evaluation workloads and measurement procedures and verify they cover all required performance areas.

## 2. Stage 1: Cross-platform runnable baseline
- [ ] 2.1 Implement the host setup script for Linux, macOS, and Windows and verify it checks for and installs missing host dependencies on each host.
  - Implemented for all three (`setup.sh`, `setup.ps1` with `setup.cmd`). Verified on macOS (ARM64) and on Windows (x86-64); Linux is not yet run.
  - On Windows the script installed QEMU and Podman with winget, created Podman's machine, and registered and re-registered the ARM build emulation. Python and the Windows Hypervisor Platform were present already, so installing those two was not exercised. With Docker Desktop installed as well, its engine did not answer on this host; the script then uses Podman.
- [ ] 2.2 Implement the startup launcher for Linux, macOS, and Windows and verify it can launch the selected target workload on each host.
  - Implemented for all three (`emu`, `emu.cmd`). Verified on macOS (ARM64) and on Windows (x86-64, with Podman as the container runtime); Linux is not yet run. Docker Desktop as the runtime on Windows is not verified.
- [x] 2.3 Build the simulated target OS container image from a Dockerfile or equivalent and verify it starts the target OS environment and an interactive prompt.
- [x] 2.4 Boot the target OS in host-native VM mode and verify the interactive prompt runs.
- [x] 2.5 Run initial CPU, memory allocation/bandwidth, and I/O workloads and verify their results are recorded with environment identity.

## 3. Stage 2: VM CPU and driver fidelity
- [x] 3.1 Implement ARM32 and ARM64 VM guest modes and verify each starts the target OS workload.
- [x] 3.2 Implement emulated, mocked, and host-routed driver-feature strategies in container and VM modes and verify each strategy in both modes.

## 4. Stage 3: Graphics support
- [ ] 4.1 Support Wayland, Flutter, OpenGL ES, and Vulkan workloads and verify each with a graphics workload.
  - Implemented as the `graphics-demo` workload. Verified on macOS (ARM64) and on Windows (x86-64), with the same outcome on both: Wayland and OpenGL ES in container, host-native VM, ARM64 VM and ARM32 VM modes; Vulkan and Flutter in container, host-native VM and ARM64 VM modes.
  - Open: Vulkan in ARM32 VM mode. With emulated graphics Vulkan is rendered by Mesa's CPU driver, which crashes on 32-bit ARM. With Debian 13's Mesa 25.0, which the image uses, Debian's own `vkcube` demo crashes too. With Mesa 26.1 from Debian backports `vkcube` runs, but this project's test still crashes inside the driver, although the Khronos validation layers find no fault in it.
  - Open: Flutter in ARM32 VM mode. The Flutter SDK builds Linux applications for x86-64 and ARM64 only, so the ARM32 image has no Flutter workload.
  - Open: the Wayland compositor is not stable in ARM32 VM mode. On Windows (x86-64) the compositor process ended, without a message in its log, in 2 of 12 runs of the graphics workload and once in 12 rounds of the Wayland and OpenGL ES tests inside one VM. The OpenGL ES test that follows then reports a lost connection, so the `gles-vm-arm32` check fails now and then; its recorded pass on Windows is from a run in which this did not happen. Whether it happens on macOS has not been tested; the check passed there. The cause is not investigated.
- [ ] 4.2 Prefer compatible host graphics acceleration and retain emulation fallback; verify both paths.
  - Implemented: `--graphics auto|host|emulated`. `auto` uses host acceleration when the host has a compatible one (QEMU's virtio-gpu with virglrenderer in VM mode, the container engine's GPU render node in container mode) and otherwise emulates.
  - Verified on macOS (ARM64) and Windows (x86-64): emulation on request, and as the fallback of `auto`, in container and VM modes.
  - Open: the host-acceleration path is not verified on any host. macOS (ARM64) has none with the installed tools: Homebrew's QEMU is built without the GPU-accelerated display device, and the container engine's virtual machine has no GPU. In container mode on Windows, Podman's engine in WSL has no GPU render node.
  - Open: host acceleration in VM mode on Windows. It ran there for the first time (QEMU 11.1.0, NVIDIA GPU): the target rendered OpenGL ES and Flutter on the host GPU through virglrenderer, Vulkan stayed on the target CPU, and virglrenderer reported errors for some of Flutter's commands. But QEMU's display without a window (`egl-headless`) stayed black, so no frame reached the emulator's display. The launcher therefore reports host acceleration as unavailable on Windows and falls back to emulation. It needs a display that shows the frame (the windowed display of stage 6 is a candidate), or a host such as Linux with QEMU's OpenGL modules.
  - QEMU refuses to capture the display over its machine protocol while the display is a texture on the host GPU. For host acceleration the launcher now reads the capture from QEMU's VNC server. That capture is confirmed against the emulated display; on Windows it returns the black display described above, and it has not been run on a host where the accelerated display works.
- [x] 4.3 Support 720p, 1080p, and 4K rendering and verify each selected resolution.
  - Verified with emulated graphics in all four modes, on macOS (ARM64) and on Windows (x86-64), by capturing the emulator's display at each resolution. ARM32 VM mode is covered with Wayland and OpenGL ES only (see 4.1).

## 5. Stage 4: Media playback
- [ ] 5.1 Accept MP2TS, MP4, and MSE-style fragment input and verify each media input path.
- [ ] 5.2 Decode MPEG-2, AVC, and HEVC video and MP2, AC-3, AAC, and HE-AAC audio; verify each codec.
- [ ] 5.3 Render decoded video through the supported graphics technologies and route audio through the host OS path; verify runtime mute and unmute.

## 6. Stage 5: Browser evaluation
- [ ] 6.1 Include WPE WebKit in the Linux client OS image and verify it launches.
- [ ] 6.2 Run web-performance workloads in WPE WebKit, including MSE playback, and verify playback results are recorded.

## 7. Stage 6: Windowed display UX
- [ ] 7.1 Implement windowed and full-screen modes with a hotkey to switch between them and verify both transitions.
- [ ] 7.2 Scale the display when the window is resized and verify the compact toolbar can mute audio and restore 1:1 pixel density.

## 8. Stage 7: Full qualification and report
- [ ] 8.1 Run the complete supported host OS, host CPU architecture, emulator mode, and VM guest architecture matrix and verify all required performance areas are measured or marked unavailable.
- [ ] 8.2 Produce the Slidev comparison with pros, cons, and actual results for each evaluated combination; verify unavailable results are explicit and no estimates are presented as measurements.

## Verification status

Checked tasks were verified with `./emu verify` on two hosts so far: macOS on ARM64, and Windows on x86-64 with Podman as the container runtime. `evaluation/verification/` records each check per host, as passed, failed, or unavailable on that host. The two hosts were verified at different revisions of the target image; each record names the image definition it ran. Run `./setup.sh` and `./emu verify` on Linux and on an x86-64 Mac to extend the coverage; tasks 2.1 and 2.2 stay open until then, and task 4.2 until a host has shown an accelerated frame on the emulator's display.
