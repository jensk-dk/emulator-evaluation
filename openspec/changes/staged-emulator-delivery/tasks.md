# Tasks

## 1. Stage 0: Evaluation foundation
- [x] 1.1 Define the supported host OS and CPU test matrix and verify it covers every declared host combination.
- [x] 1.2 Select or build the Linux client OS image, verify it boots in VM mode, and record its source or build revision.
- [x] 1.3 Define versioned evaluation workloads and measurement procedures and verify they cover all required performance areas.

## 2. Stage 1: Cross-platform runnable baseline
- [ ] 2.1 Implement the host setup script for Linux, macOS, and Windows and verify it checks for and installs missing host dependencies on each host.
  - Implemented for all three (`setup.sh`, `setup.ps1`). Verified on macOS (ARM64) only; Linux and Windows are not yet run.
- [ ] 2.2 Implement the startup launcher for Linux, macOS, and Windows and verify it can launch the selected target workload on each host.
  - Implemented for all three (`emu`, `emu.cmd`). Verified on macOS (ARM64) only; Linux and Windows are not yet run.
- [x] 2.3 Build the simulated target OS container image from a Dockerfile or equivalent and verify it starts the target OS environment and an interactive prompt.
- [x] 2.4 Boot the target OS in host-native VM mode and verify the interactive prompt runs.
- [x] 2.5 Run initial CPU, memory allocation/bandwidth, and I/O workloads and verify their results are recorded with environment identity.

## 3. Stage 2: VM CPU and driver fidelity
- [x] 3.1 Implement ARM32 and ARM64 VM guest modes and verify each starts the target OS workload.
- [x] 3.2 Implement emulated, mocked, and host-routed driver-feature strategies in container and VM modes and verify each strategy in both modes.

## 4. Stage 3: Graphics support
- [ ] 4.1 Support Wayland, Flutter, OpenGL ES, and Vulkan workloads and verify each with a graphics workload.
- [ ] 4.2 Prefer compatible host graphics acceleration and retain emulation fallback; verify both paths.
- [ ] 4.3 Support 720p, 1080p, and 4K rendering and verify each selected resolution.

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

Checked tasks were verified with `./emu verify` on one host so far: macOS on ARM64. `evaluation/verification/` records each check per host. Run `./setup.sh` (or `setup.ps1`) and `./emu verify` on Linux, Windows, and an x86-64 Mac to extend the coverage; tasks 2.1 and 2.2 stay open until then.
