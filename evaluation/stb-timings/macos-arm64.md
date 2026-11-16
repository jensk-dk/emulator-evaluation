Host macos-arm64. Median (smallest to largest, how many times).

| What | Container | VM, host-native | VM, ARM64 | VM, ARM32 |
|---|---|---|---|---|
| Image, and when taken | 0.6.0, 2026-11-15 | 0.6.0, 2026-11-15 | 0.6.0, 2026-11-15 | 0.6.0, 2026-11-16 |
| Launch to the home screen | 0.93 s (0.88 to 1.16, 3 times) | 1.32 s (1.24 to 1.90, 3 times) | 11.8 s (11.6 to 12.0, 3 times) | 29.7 s (28.7 to 31.5, 3 times) |
| of that, until the target has started the workload | 0.80 s (0.74 to 1.02, 3 times) | 1.15 s (1.07 to 1.63, 3 times) | 8.39 s (8.29 to 8.67, 3 times) | 25.7 s (24.8 to 27.6, 3 times) |
| Home screen to the first key taken | 0.12 s (0.11 to 0.12, 3 times) | 0.11 s (0.11 to 0.11, 3 times) | 3.08 s (3.08 to 3.09, 3 times) | 4.06 s (3.14 to 4.15, 3 times) |
| Switch off to the emulator ended | 0.79 s (0.76 to 0.79, 3 times) | 0.62 s (0.62 to 0.77, 3 times) | 0.83 s (0.78 to 1.15, 3 times) | 1.09 s (0.99 to 1.21, 3 times) |
| Move the selection: reported | 0.007 s (0.004 to 0.010, 20 times) | 0.005 s (0.003 to 0.010, 20 times) | 0.041 s (0.028 to 0.066, 20 times) | 0.046 s (0.034 to 0.067, 20 times) |
| Move the selection: seen in the window | 0.078 s (0.067 to 0.093, 20 times) | 0.12 s (0.05 to 0.34, 20 times) | 0.94 s (0.45 to 1.03, 20 times) | 1.16 s (1.11 to 1.28, 20 times) |
| the same after 5 s without a new picture | 0.093 s (0.092 to 0.143, 3 times) | 0.51 s (0.22 to 0.92, 3 times) | 0.65 s (0.64 to 0.97, 3 times) | 0.84 s (0.73 to 1.04, 3 times) |
| the same after 30 s without a new picture | 0.15 s (0.13 to 0.17, 3 times) | 0.67 s (0.55 to 0.87, 3 times) | 1.84 s (0.66 to 1.86, 3 times) | 2.45 s (2.11 to 2.58, 3 times) |
| Open a screen (OK): reported | 0.008 s (0.007 to 0.009, 5 times) | 0.006 s (0.006 to 0.009, 5 times) | 0.049 s (0.048 to 0.061, 5 times) | 0.056 s (0.045 to 0.070, 5 times) |
| Open a screen (OK): seen in the window | 0.088 s (0.081 to 0.103, 5 times) | 0.21 s (0.10 to 0.57, 5 times) | 1.01 s (0.50 to 1.25, 5 times) | 1.18 s (1.04 to 1.24, 5 times) |
| Return (BACK): reported | 0.008 s (0.007 to 0.008, 5 times) | 0.006 s (0.006 to 0.007, 5 times) | 0.049 s (0.047 to 0.052, 5 times) | 0.058 s (0.050 to 0.061, 5 times) |
| Return (BACK): seen in the window | 0.093 s (0.072 to 0.102, 5 times) | 0.25 s (0.10 to 0.65, 5 times) | 0.99 s (0.49 to 1.09, 5 times) | 1.20 s (1.17 to 1.31, 5 times) |
| First channel from the list: its picture in the window | 0.36 s (1 time) | 0.73 s (1 time) | 9.94 s (1 time) | 10.5 s (1 time) |
| Channel change (Up): reported as playing | 0.097 s (0.081 to 0.133, 12 times) | 0.092 s (0.083 to 0.145, 12 times) | 1.06 s (0.95 to 1.19, 12 times) | 1.23 s (1.04 to 1.38, 12 times) |
| Channel change (Up): its picture in the window | 0.16 s (0.14 to 0.19, 12 times) | 0.28 s (0.14 to 0.31, 12 times) | 2.30 s (2.09 to 2.74, 12 times) | 3.03 s (2.55 to 3.97, 12 times) |
| of those, to channel 1 (MPEG-2) | 0.17 s (0.16 to 0.18, 4 times) | 0.29 s (0.16 to 0.31, 4 times) | 2.10 s (2.10 to 2.29, 4 times) | 2.91 s (2.55 to 3.76, 4 times) |
| of those, to channel 2 (AVC) | 0.17 s (0.14 to 0.19, 4 times) | 0.28 s (0.21 to 0.31, 4 times) | 2.53 s (2.32 to 2.72, 4 times) | 2.83 s (2.71 to 3.97, 4 times) |
| of those, to channel 3 (HEVC) | 0.15 s (0.15 to 0.17, 4 times) | 0.20 s (0.14 to 0.31, 4 times) | 2.30 s (2.09 to 2.74, 4 times) | 3.23 s (2.95 to 3.75, 4 times) |
| Pictures a second in the window, channel 1 (MPEG-2) | 24.8 | 14.2 | 1.5 | 0.9 |
| Pictures a second in the window, channel 2 (AVC) | 24.6 | 17.0 | 1.5 | 0.7 |
| Pictures a second in the window, channel 3 (HEVC) | 24.6 | 14.5 | 1.4 | 0.8 |
| Start the video on demand application: its titles reported | 0.16 s (0.16 to 0.17, 3 times) | 0.17 s (0.16 to 0.17, 3 times) | 0.46 s (0.39 to 0.66, 3 times) | 0.40 s (0.37 to 0.69, 3 times) |
| Start the video on demand application: seen in the window | 0.18 s (0.17 to 0.21, 3 times) | 0.43 s (0.27 to 0.52, 3 times) | 0.97 s (0.95 to 1.24, 3 times) | 1.23 s (1.08 to 1.62, 3 times) |
| Leave it (BACK): the app launcher reported | 0.15 s (0.15 to 0.15, 3 times) | 0.15 s (0.15 to 0.17, 3 times) | 0.30 s (0.30 to 0.31, 3 times) | 0.28 s (0.28 to 0.30, 3 times) |
| Test title: OK to the stream's description read | 0.091 s (0.090 to 0.125, 3 times) | 0.15 s (0.06 to 0.17, 3 times) | 0.64 s (0.62 to 1.45, 3 times) | 0.78 s (0.50 to 1.74, 3 times) |
| Test title: OK to reported as playing | 0.13 s (0.12 to 0.15, 3 times) | 0.17 s (0.13 to 0.19, 3 times) | 1.44 s (1.35 to 2.41, 3 times) | 1.83 s (1.53 to 2.92, 3 times) |
| Test title: the last representation shown, and when | 1280x720 after 2.2 s; 1280x720 after 2.1 s; 1280x720 after 2.1 s | 1280x720 after 2.4 s; 1280x720 after 2.5 s; 1280x720 after 2.3 s | 1280x720 after 4.6 s; 1280x720 after 3.8 s; 1280x720 after 3.7 s | 1280x720 after 5.2 s; 1280x720 after 3.8 s; 1280x720 after 4.1 s |
| Test title: the browser's last count of frames | 246 frames, 1 dropped, at 9.9 s of the title; 247 frames, 1 dropped, at 9.9 s of the title; 247 frames, 1 dropped, at 9.9 s of the title | 242 frames, 1 dropped, at 9.7 s of the title; 242 frames, 1 dropped, at 9.7 s of the title; 243 frames, 1 dropped, at 9.7 s of the title | 434 frames, 2 dropped, at 18 s of the title; 448 frames, 2 dropped, at 18.7 s of the title; 446 frames, 2 dropped, at 18.6 s of the title | 405 frames, 3 dropped, at 17.4 s of the title; 430 frames, 2 dropped, at 18.5 s of the title; 419 frames, 3 dropped, at 18.2 s of the title |
| Big Buck Bunny: OK to the stream's description read | 0.012 s (0.011 to 0.167, 3 times) | 0.047 s (0.014 to 0.197, 3 times) | 0.75 s (0.74 to 1.35, 3 times) | 0.75 s (0.70 to 1.47, 3 times) |
| Big Buck Bunny: OK to reported as playing | 0.043 s (0.035 to 0.216, 3 times) | 0.093 s (0.066 to 0.243, 3 times) | 1.58 s (1.41 to 2.00, 3 times) | 1.52 s (1.45 to 2.51, 3 times) |
| Big Buck Bunny: the last representation shown, and when | 1920x1080 after 4.2 s; 1920x1080 after 4.1 s; 1920x1080 after 4.0 s | 1920x1080 after 4.6 s; 1920x1080 after 4.4 s; 1920x1080 after 4.4 s | 1920x1080 after 6.3 s; 1920x1080 after 6.1 s; 1920x1080 after 5.9 s | 1920x1080 after 7.2 s; 1920x1080 after 5.7 s; 1920x1080 after 5.8 s |
| Big Buck Bunny: the browser's last count of frames | 595 frames, 0 dropped, at 19.8 s of the title; 588 frames, 0 dropped, at 20 s of the title; 590 frames, 0 dropped, at 20 s of the title | 425 frames, 0 dropped, at 14.6 s of the title; 568 frames, 0 dropped, at 19.8 s of the title; 576 frames, 0 dropped, at 19.8 s of the title | 209 frames, 12 dropped, at 58 s of the title; 267 frames, 36 dropped, at 58.5 s of the title; 152 frames, 24 dropped, at 58.6 s of the title | 117 frames, 2 dropped, at 57.6 s of the title; 97 frames, 4 dropped, at 58.7 s of the title; 128 frames, 2 dropped, at 58.5 s of the title |
| After a workload that took the display: the results screen | 0.16 s (0.15 to 0.17, 9 times) | 0.11 s (0.09 to 0.15, 9 times) | 2.50 s (2.43 to 2.56, 9 times) | 2.68 s (2.62 to 3.44, 9 times) |
| and from there to the first key taken | 0.16 s (0.11 to 0.21, 9 times) | 0.091 s (0.007 to 0.120, 9 times) | 1.11 s (1.05 to 1.23, 9 times) | 2.08 s (1.07 to 2.15, 9 times) |

| Workload | Mode | From the user interface | As the launcher runs it, with the window | Recorded, without a window | User interface against launcher with the window | Launcher with the window against recorded |
|---|---|---|---|---|---|---|
| bench 1.0.0 | Container | 3 runs, status 0, 20.2 s (20.2 to 20.3, 3 times) | 3 runs, status 0, 20.3 s (20.3 to 20.3, 3 times) | 3 runs on image 0.1.0, 20.3 s (20.3 to 20.3, 3 times) | 13 results: 7 within 5%, 10 within 10%, ratios 0.85 to 1.30 | 13 results: 10 within 5%, 11 within 10%, ratios 0.95 to 1.92 |
| graphics-demo 1.0.0 | Container | 3 runs, status 0, 21.3 s (21.2 to 21.7, 3 times) | 3 runs, status 0, 22.0 s (22.0 to 22.1, 3 times) | 3 runs on image 0.2.0, 21.9 s (21.8 to 21.9, 3 times) | 4 results: 4 within 5%, 4 within 10%, ratios 1.00 to 1.04 | 4 results: 2 within 5%, 3 within 10%, ratios 0.79 to 0.99 |
| media-decode 1.0.0 | Container | 3 runs, status 0, 87.3 s (87.2 to 87.3, 3 times) | 3 runs, status 0, 87.9 s (87.7 to 87.9, 3 times) | 3 runs on image 0.3.0, 86.8 s (86.6 to 86.9, 3 times) | 26 results: 26 within 5%, 26 within 10%, ratios 0.97 to 1.01 | 26 results: 26 within 5%, 26 within 10%, ratios 0.98 to 1.01 |
| web-bench 1.1.0 | Container | 3 runs, status 0, 27.3 s (27.1 to 27.5, 3 times) | 3 runs, status 0, 27.6 s (27.5 to 27.7, 3 times) | 3 runs on image 0.4.0, 27.2 s (27.1 to 27.2, 3 times) | 5 results: 4 within 5%, 4 within 10%, ratios 0.71 to 1.04 | 5 results: 4 within 5%, 4 within 10%, ratios 0.87 to 1.00 |
| bench 1.0.0 | VM, host-native | 3 runs, status 0, 20.3 s (20.2 to 20.4, 3 times) | 3 runs, status 0, 20.4 s (20.3 to 21.0, 3 times) | 3 runs on image 0.1.0, 20.3 s (20.2 to 20.6, 3 times) | 13 results: 9 within 5%, 11 within 10%, ratios 0.60 to 1.05 | 13 results: 7 within 5%, 11 within 10%, ratios 0.88 to 1.13 |
| graphics-demo 1.0.0 | VM, host-native | 3 runs, status 0, 21.1 s (21.0 to 21.7, 3 times) | 3 runs, status 0, 22.0 s (22.0 to 22.1, 3 times) | 3 runs on image 0.2.0, 21.8 s (21.8 to 21.9, 3 times) | 4 results: 4 within 5%, 4 within 10%, ratios 1.00 to 1.02 | 4 results: 3 within 5%, 3 within 10%, ratios 0.89 to 0.99 |
| media-decode 1.0.0 | VM, host-native | 3 runs, status 0, 85.9 s (85.7 to 85.9, 3 times) | 3 runs, status 0, 86.4 s (86.3 to 86.5, 3 times) | 3 runs on image 0.3.0, 85.9 s (85.8 to 85.9, 3 times) | 25 results: 25 within 5%, 25 within 10%, ratios 0.99 to 1.02 | 25 results: 25 within 5%, 25 within 10%, ratios 0.97 to 1.02 |
| web-bench 1.1.0 | VM, host-native | 3 runs, status 0, 26.7 s (26.7 to 27.0, 3 times) | 3 runs, status 0, 27.4 s (27.2 to 27.4, 3 times) | 3 runs on image 0.4.0, 27.2 s (27.2 to 27.5, 3 times) | 4 results: 3 within 5%, 3 within 10%, ratios 0.55 to 1.03 | 5 results: 3 within 5%, 4 within 10%, ratios 0.83 to 1.00 |
| bench 1.0.0 | VM, ARM64 | 3 runs, status 0, 21.0 s (21.0 to 21.1, 3 times) | 3 runs, status 0, 21.6 s (21.6 to 21.7, 3 times) | 3 runs on image 0.1.0, 21.4 s (21.4 to 21.4, 3 times) | 13 results: 3 within 5%, 4 within 10%, ratios 0.65 to 0.99 | 13 results: 13 within 5%, 13 within 10%, ratios 0.97 to 1.03 |
| graphics-demo 1.0.0 | VM, ARM64 | 3 runs, status 0, 33.8 s (32.2 to 42.7, 3 times) | 3 runs, status 0, 44.6 s (44.2 to 45.2, 3 times) | 3 runs on image 0.2.0, 44.9 s (44.5 to 45.2, 3 times) | 4 results: 4 within 5%, 4 within 10%, ratios 0.97 to 1.00 | 4 results: 1 within 5%, 2 within 10%, ratios 0.64 to 1.04 |
| media-decode 1.0.0 | VM, ARM64 | 3 runs, status 0, 182.3 s (181.7 to 184.5, 3 times) | 3 runs, status 0, None, 799.1 s (189.1 to 956.9, 3 times) | 3 runs on image 0.3.0, 183.2 s (183.1 to 183.3, 3 times) | 26 results: 26 within 5%, 26 within 10%, ratios 0.98 to 1.04 | 26 results: 21 within 5%, 26 within 10%, ratios 0.93 to 1.04 |
| web-bench 1.1.0 | VM, ARM64 | 3 runs, status 0, 50.6 s (50.5 to 59.0, 3 times) | 3 runs, status 0, 60.7 s (60.7 to 61.4, 3 times) | 3 runs on image 0.4.0, 60.1 s (59.8 to 60.3, 3 times) | 5 results: 3 within 5%, 3 within 10%, ratios 0.51 to 1.34 | 5 results: 5 within 5%, 5 within 10%, ratios 0.99 to 1.01 |
| bench 1.0.0 | VM, ARM32 | 3 runs, status 0, 25.5 s (24.6 to 25.7, 3 times) | 3 runs, status 0, 25.4 s (25.3 to 25.4, 3 times) | 3 runs on image 0.1.0, 25.0 s (25.0 to 25.0, 3 times) | 13 results: 0 within 5%, 3 within 10%, ratios 0.70 to 1.09 | 13 results: 13 within 5%, 13 within 10%, ratios 0.96 to 1.01 |
| graphics-demo 1.0.0 | VM, ARM32 | 3 runs, status 0, 14.1 s (14.0 to 17.5, 3 times) | 3 runs, status 0, 19.4 s (19.1 to 19.6, 3 times) | 3 runs on image 0.2.0, 19.5 s (19.2 to 19.9, 3 times) | 2 results: 0 within 5%, 1 within 10%, ratios 0.94 to 1.11 | 2 results: 0 within 5%, 1 within 10%, ratios 0.64 to 0.95 |
| media-decode 1.0.0 | VM, ARM32 | 3 runs, status 0, 195.3 s (190.8 to 200.3, 3 times) | 3 runs, status 0, 212.5 s (192.7 to 221.5, 3 times) | 3 runs on image 0.3.0, 229.1 s (211.0 to 229.7, 3 times) | 20 results: 7 within 5%, 13 within 10%, ratios 0.85 to 1.22 | 20 results: 12 within 5%, 16 within 10%, ratios 0.82 to 1.02 |
| web-bench 1.1.0 | VM, ARM32 | 3 runs, status 0, 54.8 s (53.9 to 63.1, 3 times) | 3 runs, status 0, 68.3 s (66.6 to 68.9, 3 times) | 3 runs on image 0.4.0, 67.1 s (66.2 to 67.9, 3 times) | 5 results: 3 within 5%, 3 within 10%, ratios 0.47 to 1.27 | 5 results: 4 within 5%, 4 within 10%, ratios 0.99 to 1.37 |

A status other than 0: the workload failed, or (None) the emulator ended before the workload reported how it ended; the results it had reported by then are counted.

From the user interface against the launcher with the window, more than 10% apart (the two medians, and their ratio):
- bench, Container, seq_read: 9732.582, 11480.067, 0.85
- bench, Container, seq_write: 2553.939, 2838.044, 0.90
- bench, Container, sync_write_4k: 5299.245, 4067.999, 1.30
- web-bench, Container, web_launch web 1920x1080: 0.184, 0.258, 0.71
- bench, VM, host-native, seq_read: 12050.367, 13442.672, 0.90
- bench, VM, host-native, seq_write: 2165.609, 3585.432, 0.60
- media-decode, VM, host-native, playback_dropped_frames avc-mp4/vulkan vulkan 1920x1080: 0, 1
- web-bench, VM, host-native, mse_playback_dropped_frames mpeg2-fragments web 1920x1080: 1, 0
- web-bench, VM, host-native, web_launch web 1920x1080: 0.142, 0.258, 0.55
- bench, VM, ARM64, malloc_churn: 3.097, 3.57, 0.87
- bench, VM, ARM64, matmul_f64: 516.484, 627.01, 0.82
- bench, VM, ARM64, page_fault: 188.982, 212.441, 0.89
- bench, VM, ARM64, rand_read_4k: 9017.805, 11858.031, 0.76
- bench, VM, ARM64, rand_write_4k: 8289.908, 11245.691, 0.74
- bench, VM, ARM64, seq_read: 2611.046, 4044.106, 0.65
- bench, VM, ARM64, sha256_1t: 70.653, 82.278, 0.86
- bench, VM, ARM64, sha256_mt: 226.33, 286.665, 0.79
- bench, VM, ARM64, sync_write_4k: 1374.669, 1985.151, 0.69
- web-bench, VM, ARM64, web_launch web 1920x1080: 3.176, 6.278, 0.51
- web-bench, VM, ARM64, web_render_fps web 1920x1080: 1.27, 0.95, 1.34
- bench, VM, ARM32, malloc_churn: 2.441, 2.957, 0.83
- bench, VM, ARM32, matmul_f64: 372.623, 470.078, 0.79
- bench, VM, ARM32, page_fault: 63.291, 90.941, 0.70
- bench, VM, ARM32, rand_read_4k: 5294.81, 7392.817, 0.72
- bench, VM, ARM32, rand_write_4k: 4830.062, 6781.989, 0.71
- bench, VM, ARM32, seq_read: 2238.408, 2822.181, 0.79
- bench, VM, ARM32, sha256_1t: 110.995, 128.682, 0.86
- bench, VM, ARM32, sha256_mt: 340.665, 418.052, 0.81
- bench, VM, ARM32, stream_triad: 4411.663, 5022.104, 0.88
- bench, VM, ARM32, sync_write_4k: 623.405, 853.784, 0.73
- graphics-demo, VM, ARM32, gles_fps gles 1920x1080: 1.59, 1.43, 1.11
- media-decode, VM, ARM32, audio_decode_speed audio-aac-mp4: 80.21, 70.26, 1.14
- media-decode, VM, ARM32, audio_decode_speed audio-heaac-mp2ts: 34.53, 29.99, 1.15
- media-decode, VM, ARM32, audio_decode_speed audio-heaac-mp4: 34.58, 30.32, 1.14
- media-decode, VM, ARM32, playback_dropped_frames avc-mp4/wayland wayland 1920x1080: 94, 77, 1.22
- media-decode, VM, ARM32, playback_dropped_frames hevc-fragments/wayland wayland 1920x1080: 68, 80, 0.85
- media-decode, VM, ARM32, video_decode_speed mpeg2-fragments 1280x720: 14.26, 12.83, 1.11
- media-decode, VM, ARM32, video_decode_speed mpeg2-mp2ts 1280x720: 14.26, 12.82, 1.11
- web-bench, VM, ARM32, web_launch web 1920x1080: 3.392, 7.212, 0.47
- web-bench, VM, ARM32, web_render_fps web 1920x1080: 0.33, 0.26, 1.27

The launcher with the window against the recorded results, more than 10% apart (the two medians, and their ratio):
- bench, Container, seq_write: 2838.044, 2435.555, 1.17
- bench, Container, sync_write_4k: 4067.999, 2121.058, 1.92
- graphics-demo, Container, wayland_fps wayland 1920x1080: 1183.35, 1505.84, 0.79
- web-bench, Container, web_render_fps web 1920x1080: 44.6, 51.24, 0.87
- bench, VM, host-native, rand_read_4k: 51148.69, 57908.347, 0.88
- bench, VM, host-native, sync_write_4k: 6580.326, 5799.603, 1.13
- graphics-demo, VM, host-native, vulkan_fps vulkan 1920x1080: 163.46, 182.89, 0.89
- media-decode, VM, host-native, playback_dropped_frames avc-mp4/vulkan vulkan 1920x1080: 1, 0
- web-bench, VM, host-native, web_render_fps web 1920x1080: 35.56, 43.09, 0.83
- graphics-demo, VM, ARM64, vulkan_fps vulkan 1920x1080: 3.06, 3.5, 0.87
- graphics-demo, VM, ARM64, wayland_fps wayland 1920x1080: 110.13, 173.39, 0.64
- graphics-demo, VM, ARM32, wayland_fps wayland 1920x1080: 114.07, 177.4, 0.64
- media-decode, VM, ARM32, audio_decode_speed audio-aac-mp4: 70.26, 79.09, 0.89
- media-decode, VM, ARM32, audio_decode_speed audio-heaac-mp2ts: 29.99, 34.25, 0.88
- media-decode, VM, ARM32, audio_decode_speed audio-heaac-mp4: 30.32, 34.68, 0.87
- media-decode, VM, ARM32, playback_dropped_frames hevc-fragments/wayland wayland 1920x1080: 80, 98, 0.82
- web-bench, VM, ARM32, web_render_fps web 1920x1080: 0.26, 0.19, 1.37
