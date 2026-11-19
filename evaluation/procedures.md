# Measurement procedures

How performance results are produced, so that a result from one host can be
compared with a result from another. The workloads are defined in
[workloads.json](workloads.json) and the combinations to cover in
[matrix.json](matrix.json).

## Rules for every measurement

1. **One combination at a time.** A run measures one host, one host CPU
   architecture and one emulator mode (`container`, `vm-native`, `vm-arm32`,
   `vm-arm64`).
2. **Fixed emulator size.** 4 CPUs and 2048 MiB of memory (the launcher's
   defaults) unless the result is explicitly about another size. In container
   mode the container engine must have at least that much; the engine's own
   CPU count and memory are recorded with the result.
3. **Quiet host.** Mains power, no other emulator or build running, and
   nothing else competing for the CPU or disk.
4. **Current image.** The launcher rebuilds the client OS image when its
   definition has changed. Never measure with a hand-modified image.
5. **Three runs, report the median.** Start the emulator fresh for each run
   (`--repeat 3`). Each run is recorded separately; the comparison uses the
   median of each test and shows the spread.
6. **Record, do not transcribe.** Results are written by the launcher
   (`--record`) to `evaluation/results/`. Numbers are never typed in by hand.
7. **Unavailable is a result.** When a combination or test cannot be run,
   that is stated with the reason. A test that fails inside the target
   reports `"value": null` and an `"unavailable"` reason. Nothing is
   estimated or carried over from another combination.
8. **Same workload version.** Only results from the same workload version
   are compared. A workload's version changes when its method changes.

## What identifies a result

Every record in `evaluation/results/` carries:

| Field | Identifies |
|---|---|
| `host` | host id (OS and CPU architecture) and machine id (`machine`), host OS and version, CPU architecture, CPU model, CPU count, memory, GPUs with their drivers (`gpus`; absent in records made before it was added) |
| `emulator` | mode and variant, guest architecture, accelerator, CPU model, runtime and its version, CPUs, memory, options; for runs with a display, its resolution and whether graphics were emulated or mapped to the host, with the reason |
| `image` | client OS image name and version, its source (Debian release, base image digest, apt snapshot), the SHA-256 of its build definition, the repository revision it was built from, and the SHA-256 of the root filesystem or the container image ID; plus what the running target reported about itself |
| `workload` | workload id, version and arguments |
| `boot_seconds` | time from starting the emulator until the target OS reported ready |

`./emu verify results` fails if any record lacks one of these.

**Machines.** Results and verification records are kept apart by host id and
machine id together, written `HOST@MACHINE` (`linux-x86_64@intel-core-i7-10700k`).
The launcher makes the machine id from the CPU model. A machine that starts
two host operating systems so has the same id under both, and the results
page says that the two hosts are one machine. Two machines with the same host
OS get different ids unless their CPU models are the same: then, and whenever
another name is wanted, set `EMU_MACHINE` to a name for the machine on every
run of the launcher there (`EMU_MACHINE=lab-pc-2 ./emu verify`). A record
made before the id was recorded (2026-11-18) is read with the id its CPU
model gives. A verification record is the file
`evaluation/verification/HOST_MACHINE.json`, the timings of the STB simulator
are `evaluation/stb-timings/HOST_MACHINE_MODE.json`, and
[machines.json](results/machines.json) states what is known about a machine
under its machine id. The known issues, the disk space and time tables and
the matrix still name host ids: they hold for a host OS, whatever the
machine.

## Resource benchmarks

Workload `bench` (CPU, memory allocation, memory bandwidth, I/O).

    ./emu run --mode container --workload bench --record --repeat 3
    ./emu run --mode vm --arch native --workload bench --record --repeat 3
    ./emu run --mode vm --arch arm64 --workload bench --record --repeat 3
    ./emu run --mode vm --arch arm32 --workload bench --record --repeat 3

- Every test runs for a fixed wall-clock time (2 seconds by default,
  `--seconds`), so the suite takes about as long under CPU emulation as it
  does natively.
- I/O tests run on `/data`, the target's writable data partition. In VM mode
  that is an ext4 filesystem on a virtio disk backed by a raw file on the
  host, formatted at boot. In container mode it is a volume of the container
  engine. The I/O results therefore describe the emulator's storage path, not
  the host disk alone.
- Reads use `O_DIRECT` so the target's page cache is not what is measured;
  each I/O result says whether direct I/O was in effect.

## Functional checks

Workload `prompt` starts an interactive shell on the target OS. The automated
check types a command into it and expects the computed answer back
(`./emu verify prompt-container prompt-vm`).

### The launcher's other commands and the setup script

Checks for requirements that were written on 2026-11-17 for what had been
built without one (task 9.2). None of them is a measurement.

    ./emu verify doctor report-serve report-page build-cleanup setup-check vm-x86_64

- **What the launcher finds on the host** (`doctor`). The command must say
  something about the host, the VM emulators, the accelerator, the container
  runtime, the sound output, the windows, graphics acceleration in VM and in
  container mode with its reason, and each target image, and its status must
  agree with whether it names something as missing. It must say for each
  simulated ARM target whether it is set up. Then one program at a time is
  hidden from the launcher, as a stand-in for a host without it; nothing is
  removed for that. Without the emulator for the host's own CPU the command
  must name it as missing, point to the setup script and report failure.
  Without the ARM32 emulator it must say that the ARM32 target is not set
  up, name the setup option, name no missing dependency for it, and end as
  it did before: what only the simulated ARM targets need is set up on
  request.
- **The results page is served** (`report-serve`). The results command is
  started on a port of its own, without a browser. Over one connection, which
  the server must keep open, the check reads the page, the list of records
  and every record, the verification records, the known issues, what is
  stated about the machines, and the disk space and time values; the list
  must be the record files. The server must not answer on the host's own
  network address.
- **The results page shows every record** (`report-page`). Chrome, Chromium
  or Edge renders the page without a window and prints what it made of it.
  The page must say that it shows as many records as there are record files
  and that none could not be read, and must have the hosts, the support
  matrix with the known issues, charts, and the tables of disk space and
  times. Without such a browser the check is "unavailable": none of them is a
  host dependency. Not checked: choosing the hosts, relative values, what
  pointing at a row shows, and the PDF.
- **Clean-up after a build** (`build-cleanup`). Three stand-ins are put in
  the container engine: the current container image under the project's name
  with another version, an unnamed image with the project's label, and the
  same image under a name that is not the project's. The clean-up must
  remove the first two, say so, and leave the third and the images of the
  current version. It must ask the engine to remove the build steps unused
  for 48 hours; the check holds that request back, so that it empties
  nothing. Like a build, the check removes real images of earlier versions
  of the project, should the engine hold any. Not checked: the option that
  keeps earlier builds, and the removal of build steps itself.
- **Setup script** (`setup-check`). The host's setup script is run twice, to
  check only and to list what the uninstall option would remove; it is never
  asked to install or to remove. Its status must agree with what it says, and
  its record of what it installed must be unchanged. Not checked: installing,
  asking before it, the optional extras and the package managers, which need
  a host where something is missing.
- **Simulated x86-64 guest** (`vm-x86_64`). The evaluation matrix must have
  no x86-64 guest mode; then the guest is started with the prompt workload
  and must report an x86-64 machine on a simulated CPU. On a host of another
  CPU architecture the check is "unavailable" unless the x86-64 target image
  has been built: it does not build it.

## Driver strategies

Workload `driver-check` reads a driver feature through its target OS
interface and reports what it observed (`./emu verify drivers-container
drivers-vm`). For `hwrng` the check proves which strategy served the read:

- `mocked`: the 16-byte sample equals the stub's fixed pattern.
- `host`: the sample appears in the byte stream the host-side process logged.
- `emulated`: no host-side process ran, and the target names the emulated
  provider (the kernel's virtio-rng driver in VM mode, the software device
  model in container mode).

## Graphics

Workload `graphics-demo`. One run measures one display resolution; run each
combination at all three.

    ./emu run --mode container --workload graphics-demo --resolution 720p --record --repeat 3
    ./emu run --mode container --workload graphics-demo --resolution 1080p --record --repeat 3
    ./emu run --mode container --workload graphics-demo --resolution 4k --record --repeat 3

and the same for `--mode vm --arch native`, `--arch arm64` and `--arch arm32`.

- Four tests, one per graphics technology: `wayland_fps` (a Wayland client
  drawing with the CPU into shared memory), `gles_fps` (OpenGL ES 2.0),
  `vulkan_fps` and `flutter_fps`. Each shows a fixed animated scene full
  screen for a fixed time (5 seconds by default, `--seconds`; `--tests`
  selects tests).
- The animation advances by frame number, so every run draws the same frames
  in the same order however fast it goes.
- The Wayland, OpenGL ES and Vulkan tests finish each frame and submit it
  without waiting for the display. Their `value` is frames rendered per
  second; `displayed_fps` is how many of those the compositor reported as
  shown. The Flutter test follows the display instead, as Flutter applications
  do: it draws at most one frame each time the compositor shows one, and
  reports how long building and rasterising each frame took.
- The display paces differently in the two modes, which bounds
  `displayed_fps` and the Flutter frame rate. Container mode has no display
  device; its headless compositor output simulates a 60 Hz display. VM mode's
  emulated display device has no refresh signal, so the compositor updates it
  as often as it can compose a frame.
- Each result names what rendered it (`renderer`) and whether that was host
  graphics acceleration (`accelerated`); the record's `emulator.graphics` says
  which provider the launcher selected and why. With `--graphics auto` (the
  default) the launcher uses host acceleration when the host has a compatible
  one and falls back to emulation otherwise. A comparison must only put
  results with the same provider side by side.
- A technology that the target image cannot run on an architecture reports
  `"value": null` with the reason.

`./emu verify` checks the display itself, not only what the target reports:
at the end of each test the launcher captures the emulator's display (through
QEMU in VM mode, from the compositor in container mode) and checks its size
and the marker blocks that test draws. `--screenshot DIR` saves the same
captures as PNG files.

## Audio and video decoding

Workload `media-decode`.

    ./emu run --mode container --workload media-decode --record --repeat 3
    ./emu run --mode vm --arch native --workload media-decode --record --repeat 3
    ./emu run --mode vm --arch arm64 --workload media-decode --record --repeat 3
    ./emu run --mode vm --arch arm32 --workload media-decode --record --repeat 3

- **Reference streams.** Built with the image by
  [target/media/build-media.sh](../target/media/build-media.sh): 1280x720
  video at 25 frames/s, 5 seconds, a moving test pattern; and 30-second
  audio-only streams. Each video codec (MPEG-2, AVC, HEVC) is encoded once and
  packed unchanged into each container (MP2TS, MP4, fragmented MP4 split into
  an initialisation segment and one fragment per group of pictures). The
  streams are the same on every target architecture. A result names its
  stream and the SHA-256 of the stream's bytes; the streams are part of the
  workload's version.
- **Decode speed** (`video_decode_speed`, `audio_decode_speed`, one case per
  stream). The `ffmpeg` program decodes the stream as fast as it can, on all
  of the target's CPUs, and discards the output. The value is media seconds
  decoded per second of the decoder's own running time (`x realtime`). A
  stream that decodes in well under a second is decoded again until a second
  has been timed. For the fragment cases the fragments are appended to the
  decoder's input one after another while it runs.
- **Dropped frames** (`playback_dropped_frames`, one case per stream and
  graphics technology). The stream is played once in real time, full screen,
  with its sound on the target's audio device. By default one stream per
  video codec is played, each arriving a different way (MPEG-2 in MP2TS, AVC
  in MP4, HEVC as fragments); `-- --full` plays all nine. The value is the
  number of the stream's 125 frames that were not shown:
  - Wayland, OpenGL ES and Vulkan: the mpv player's own count of frames it
    dropped, in its output and in its decoder.
  - Flutter: the `ffmpeg` program decodes in real time and hands the frames to
    the Flutter application, which always draws the newest one; frames that
    were replaced before the application could draw them are the dropped ones.
  The two counts come from different players and are not comparable with each
  other; compare a technology with itself across hosts and modes.

  Both are the players' own counts, not the display's. They were compared
  with the display's own record (the compositor's count of repaints with new
  content, see [MSE playback](#web)) on the macOS host on 2026-11-15, at 1080p
  with emulated graphics, each stream played at least once in every mode:
  - Container, host-native VM and ARM64 VM modes, every technology, and
    Wayland in ARM32 VM mode: the display showed at most three fewer new
    frames than the player counted as shown. (For Flutter it showed a few
    more: the application draws its window before the stream starts.)
  - OpenGL ES in ARM32 VM mode: mpv counted 19 to 45 of a stream's frames as
    shown, and the display showed 13 to 34, six to eleven fewer each time.
    The value understates the loss by that much. The likely cause, not
    checked: mpv is told to draw without waiting for the display
    (`--force-render`), and where the display is slower still, a frame is
    replaced by the next before it was shown.

  The value is unchanged by this: it is still the player's count. Not
  compared on the other hosts.
- Fragments are appended ahead of playback: a fragment when less than two
  seconds of media are buffered ahead of the playback position.
- The record's `emulator.graphics` and `emulator.audio` say how graphics and
  sound were provided. Results of playback with different graphics providers
  must not be put side by side.
- A sound that plays on the host is part of the run; for a measured run on a
  shared machine use `--mute` or `--option audio-output=none`.

`./emu verify` checks what the target reports against the outside: a capture
of the emulator's display during each playback must show the stream's marker
blocks (the four corners, and one whose colour names the video codec), and
the sound must arrive on the host. Each audio stream is a tone whose pitch
names its codec (MP2 440 Hz, AC-3 660 Hz, AAC 880 Hz, HE-AAC 1100 Hz). The
checks look for the pitches in a recording made on the host; for mute they
look for the silent stretch in the middle of a tone. Nothing is heard while
they run. Where the recording is made depends on the host:

- Linux: the tones are played into a private output device of the host's
  sound server (PulseAudio or PipeWire), and that device is recorded.
- macOS: there is no private output device without installing an audio
  driver. The tones are played on the default output device at volume 0. The
  launcher's player records what the system's audio queue takes for the
  device, which the queue does at the device's own pace, and reports how long
  the device played by its own clock. The check also asks the system's audio
  server whether it sees the player process playing, and on which device.
  This shows that the host's audio output took the sound; it is not a
  recording of what left the device.
- Windows: the same as on macOS, with the launcher's player for Windows. The
  tones are played on the default output device with the player's volume in
  the Windows mixer at 0 (the player puts the volume back afterwards). The
  player records what the wave output takes for the device, at the device's
  pace, and reports the device's own count of the samples it played. The
  check also asks the Windows audio service whether it has a session of the
  player process that is playing, and on which device.

The start with the mute setting and the launcher's audio command have a check
of their own (`./emu verify audio-switch-container audio-switch-vm`, task
9.2). A run is started muted, with its sound taken in and not played. While
the target plays a tone, `emu audio` is given for that run by its id: the
state, a toggle, two seconds later another toggle, and the state again. It
must answer muted, not muted, muted and muted, and what the run's audio
process recorded as sent on to the host must be silence from the start, the
tone, and silence again. After the run has ended the command must report
failure for it. This check goes by the audio process's own record, not by a
recording on the host, which the mute check has.

## Remote control input

Functional checks of the launcher's windows and of remote control input
(tasks 7.1 to 7.5); nothing here is a measurement. The `remote-keys` workload
is their target side: it puts one full-screen window on the target's display,
a still picture with the marker blocks of the graphics workloads, and prints
a line for every key that window gets, with the key's Linux code and the
symbol the target's keymap gives it.

    ./emu run --mode container --workload remote-keys
    ./emu verify window-display-vm window-scaling-vm window-toolbar-vm window-fullscreen-vm
    ./emu verify remote-keys-vm remote-window-vm settings-window settings-launch

`./emu verify` runs the workload once per mode with the display window and
the on-screen remote control, and drives the window as a person would,
through the window's own command channel (`--control`): keys typed into it
and mouse clicks on its buttons go through Qt's event handling like real
ones. What each check goes by:

- **The display in the window** (`window-display-*`). The window saves the
  display as it arrived; the marker blocks must be where the target drew
  them. This is the picture the window holds, not a photograph of the screen:
  what is on the physical screen is not captured.
- **Scaling** (`window-scaling-*`). The window is given two sizes, one of the
  display's shape and one of another; each time it saves the part that shows
  the display, which must have the expected size and all the marker blocks.
- **Toolbar** (`window-toolbar-*`). After the 1:1 button the display must be
  drawn on as many screen pixels as it has. The mute button is pressed twice;
  each time the run's audio process is asked whether it is muted.
- **Full screen** (`window-fullscreen-*`). Ctrl+Alt+F and then F11 are typed
  into the window. It must report full screen without its toolbar, cover the
  screen and show the whole picture scaled to it, and come back as it was. A
  window that reports full screen without growing makes the check
  "unavailable", with the reason: the window system did not carry it out.
- **The toolbar's other buttons** (`window-buttons-*`). The full screen
  button is pressed, and F11 brings the window back, since full screen has no
  toolbar; the same holds as for the full screen check. The remote control
  button is pressed twice: the on-screen remote control must be hidden and
  shown again.
- **The other hotkeys** (`window-hotkeys-*`). Ctrl+Alt+R twice hides and
  shows the on-screen remote control; Ctrl+Alt+M twice mutes and unmutes,
  asked of the run's audio process each time; Ctrl+Alt+1, in a window that
  was given half the size, brings the display back to one screen pixel per
  pixel. Then OK is pressed: it must be the first key the target has got, so
  no hotkey reached it as a remote control key.
- **Host keys** (`remote-keys-*`) and **the on-screen remote control**
  (`remote-window-*`). For each of the 32 keys, its host key is typed into
  the display window, and its button is clicked; each time the target must
  print that key's code, pressed and released, and nothing else.
- **Settings window** (`settings-window`, `settings-launch`). Fields are set
  and Start is clicked; the arguments must be what the launcher's parser reads
  as those settings, and there must be a field for every argument of
  `emu run`. The command line the window shows must be the one of those
  arguments, and `emu run` with nothing set. Then the launcher is started
  without arguments, a workload is chosen in the window, and its results must
  be those of the same arguments on the command line.

Not checked: that keys stay away from the target while another window has the
focus, and anything about RedRat IR input, which is not implemented.

## STB simulator

Functional checks of the `stb-simulator` workload (tasks 7.7 to 7.10);
nothing here is a measurement. The workload shows a set-top-box-like user
interface in the target's browser and prints a line for everything the user
interface does:

    EMU-STB: {"event": "screen", "screen": "channels", "focus": "1", "items": ["1", "2", "3"]}
    EMU-STB: {"event": "channel", "state": "playing", "number": 2, "stream": "avc-fragments", ...}
    EMU-STB: {"event": "vod", "state": "representation", "title": "test-pattern", "representation": {...}}

    ./emu run --mode container --workload stb-simulator
    ./emu verify stb-start-vm stb-channels-vm stb-vod-vm stb-workloads-vm

`./emu verify` runs the workload once per mode, with the display window and
the on-screen remote control, at 720p, and operates it with remote control
keys alone, through the window's command channel as in the remote control
checks: keys typed into the window and mouse clicks on the remote control's
buttons. It waits for the line each key should bring about, and takes the
display's picture from the window. A browser that has just started shows its
page a moment before it has the keyboard, so the run first presses the red
key, which has no function and is reported, until it arrives. What each check
goes by:

- **Start and keys** (`stb-start-*`). The home screen is reported, and a
  capture of the display shows the user interface: its page colour and a
  selected item. Then a tour, once with host keys and once with clicks on
  the on-screen remote control: EXIT to the home screen; for each of the
  channel list, the app launcher and the performance tests, Up or Down to
  its entry (each move is reported), OK (its screen is reported), BACK (the
  home screen again). RedRat IR input is not implemented and not covered.
- **Channels** (`stb-channels-*`). Channel 2 is selected in the channel list
  and played, then Up (channel 3), then the digit 1 (channel 1). Each time
  the user interface must report the channel playing, a capture of the
  display must show the corner blocks of the reference streams and the block
  whose colour names that channel's video codec, and the channel's tone must
  arrive on the host: the pitch names the audio codec (880 Hz AAC, 660 Hz
  AC-3, 440 Hz MP2), and the three tones must come in the order the channels
  were played, at the launcher's host-side audio process and in the
  recording made on the host (as in "Audio and video decoding").
- **Video on demand** (`stb-vod-*`). OK on the application in the app
  launcher; the application must report dash.js and its titles, Big Buck
  Bunny and Elephants Dream among them. The test title over the slow path
  (0.6 Mbit/s) must play for three seconds showing only its smallest
  representation, and without the limit the player must go on to a larger
  one; each time a capture of the display must show the block whose colour
  names the representation the player reports. Then Big Buck Bunny is
  started from the internet: where the target reaches it, it must play for
  three seconds, and the check says at which representations; where it does
  not, the application must say so and still take keys. That is reported
  either way and does not fail the check: the stream is not this project's.
  BACK at the titles must bring the simulator's app launcher back.
- **Performance workloads** (`stb-workloads-*`). The performance tests
  screen must list every implemented performance workload of
  `evaluation/workloads.json`. Each is started with OK and must end with
  status 0, report at least one measurement to the launcher (an `EMU-RESULT`
  line with `launched_from`), and be followed by the results screen. The
  simulator is started with `--quick` for this, so each workload runs a
  short part of its tests: the results show that it ran and reported, and
  are not measurements to compare.

### Timings of the simulator

How fast the simulator starts and answers its keys, and what the performance
workloads report when they are started from its user interface, is taken by
[stb-timings.py](stb-timings.py). The stb-simulator spec asks for these since
2026-11-17 ("Time the STB simulator from the host"), and they are
not results of the performance evaluation: they are findings about the
simulator, taken with a method of that script's own, and kept apart from
`evaluation/results/` in [stb-timings](stb-timings).

    python3 evaluation/stb-timings.py run --mode container
    python3 evaluation/stb-timings.py run --mode vm --arch arm32
    python3 evaluation/stb-timings.py table > evaluation/stb-timings/HOST.md

`run` takes one mode, on a quiet host as for every measurement, and writes
`stb-timings/HOST_MACHINE_VARIANT.json`; `table` prints the files of a host on
one machine as tables.

- **The run.** The simulator is started as `./emu run --workload
  stb-simulator` starts it: at 1080p, with 4 CPUs and 2048 MiB, in the
  launcher's window, with remote control keys from the keyboard. Its sound is
  taken in by the host and not played. Keys are typed into the window
  through its command channel, as in the checks.
- **A time** runs on the host's clock from the moment a key is given to the
  window. *Reported* ends when the `EMU-STB` line for what the key brought
  about has arrived at the launcher: the way of the key into the target, the
  user interface's answer, and the way of the line back. *Seen* ends when
  the window has received a picture of the display that shows it: for a
  menu, any new picture after the screen had shown none for 0.4 s (2 s on a
  simulated ARM target); for a channel, a picture with the red corner block
  and the block that names the channel's video codec, looked for every
  20 ms (0.2 s on a simulated ARM target). Neither says when the picture
  was on the host's screen.
- **Starts.** The simulator is started three times. The time runs from the
  launcher being called to the home screen being reported, and then to the
  first key the user interface takes (the red key, pressed every 0.05 s, or
  every second on a simulated ARM target).
- **Menus.** Twenty moves of the selection on the home screen, three more
  after 5 s and three after 30 s without a new picture, and five times a
  screen opened and left.
- **Channels.** The first channel from the list, then Up through the three
  channels four times. The last time round, the pictures that reach the
  window are counted for 10 s on each channel; the streams have 25 frames a
  second. That counts what the window gets, which is no more than the way
  the display takes to it delivers.
- **Video on demand.** The application is started and left three times. The
  test title and Big Buck Bunny are each played three times, for 12 s and
  20 s after they are reported as playing (three times as long on a
  simulated ARM target), and the representations that dash.js reports as
  shown are kept with their times. Big Buck Bunny comes from the internet,
  so its times are also the connection's. Should nothing come of the OK that
  starts a title, it is pressed once more, and the run keeps that it was.
- **Performance workloads.** Each is started from the performance tests
  screen, in full, in three rounds. Then each is run as the launcher runs
  it, three times from a fresh start, with the display in the launcher's
  window as the simulator has it: results taken under the same conditions
  on the same image. `table` sets the medians of the two beside each other,
  and those of the second beside the medians of the results recorded in
  `evaluation/results/`, which were taken without a window and on earlier
  images. What it lists as apart differs by more than 10%.

So far only the macOS host has been timed (2026-11-15 and 16, image 0.6.0,
unattended and with its screen locked):
[stb-timings/macos-arm64.md](stb-timings/macos-arm64.md). What that showed
is in the [README](../README.md#stb-simulator) and, with what it showed
about the launcher's window, in the task list (7.1, 7.2 and 7.7 to 7.10).

## Web

Workload `web-bench`. The browser is WPE WebKit, started by its launcher Cog
as a Wayland client, full screen on the target's display.

    ./emu run --mode container --workload web-bench --record --repeat 3
    ./emu run --mode vm --arch native --workload web-bench --record --repeat 3
    ./emu run --mode vm --arch arm64 --workload web-bench --record --repeat 3
    ./emu run --mode vm --arch arm32 --workload web-bench --record --repeat 3

- **Pages.** The workload's own, in
  [target/rootfs/opt/emu/web](../target/rootfs/opt/emu/web). The workload
  serves them to the browser over the target's loopback interface, and a page
  reports what it measured back to the workload. The browser is started anew
  for each test and each stream, and so is the target's display service: on
  the simulated ARM32 target the compositor does not survive a second browser
  while its record is being read (see MSE playback).
- **Launch** (`web_launch`, a functional test). The browser starts, loads a
  page and runs its script; the page reports the browser's user agent, the
  size of its viewport and whether it has Media Source Extensions. The value
  is the time from starting the browser to the page's report.
- **Rendering** (`web_render_fps`). A fixed animated page
  ([render.html](../target/rootfs/opt/emu/web/render.html)): a rotating
  background, 64 blended shapes and a grid of 24 text elements, all of them
  page elements, moved once per animation frame for 5 seconds
  (`-- --seconds S`) at the display resolution (`--resolution`). The browser
  draws one frame per display refresh, so the frame rate is bounded by the
  60 Hz display, as the Flutter test's is. Reported with percentiles of the
  time between frames, and with `displayed_fps`: how often the display showed
  something new in that time, by the compositor's own record (see MSE
  playback). The value is the page's count of the frames it drew.
- **MSE playback** (`mse_playback_dropped_frames`). The fragmented streams of
  the media-decode workload, one per video codec (MPEG-2 with MP2, AVC with
  AAC, HEVC with AC-3; `-- --streams` selects). A page
  ([mse.html](../target/rootfs/opt/emu/web/mse.html)) appends a stream's
  initialisation segment and its media fragments to a Media Source buffer,
  keeping two seconds ahead of the playback position, and the browser plays
  them in real time, full screen, with their sound on the target's audio
  device. The value is the stream's frames that did not reach the display:
  all 125, less the frames shown. The frames shown are the smaller of two
  counts (`displayed_frames`):
  - the browser's (`shown_frames`): the frames it counted at its video output
    and did not drop there (`getVideoPlaybackQuality()`). The browser's own
    count of dropped frames is not the value, because it covers only frames
    that got as far as the output: under CPU emulation the decoder can skip
    most of a stream before that.
  - the display's (`display_repaints`): how often the display showed
    something new while the stream played. The target's compositor records
    every repaint and whether it had new content of a client (Weston's
    timeline, read with `weston-debug`); the workload counts those from 0.1 s
    before the browser reported the stream playing to 0.25 s after its end.
    A frame at the browser's output is not yet on the display: the browser
    still has to draw the page with it, and where that drawing is slower than
    the stream the display shows a few frames of a stream whose every frame
    the browser counted. (On a simulated ARM target on the macOS host: 125
    counted by the browser, 5 to 9 shown.)

  The result has both counts, the browser's count of dropped frames, the
  times playback stalled, and whether the sound was on. A stream the browser
  does not play is reported with `"value": null` and the browser's reason,
  and so is one whose display record cannot be read. Before version 1.1.0 of
  the workload the value was the browser's count alone; those results are not
  comparable and the results page does not chart them.
- **What is changed about the browser.** Two things, both because the target
  runs it unattended: WebKit's process sandbox is off (it needs kernel
  features a container does not give, and the browser loads nothing but the
  workload's pages), and those pages may start media with sound, which WebKit
  otherwise allows only after a click
  ([target/src/emu_web_autoplay.c](../target/src/emu_web_autoplay.c)).
- **Graphics provider.** As for the graphics workload: results with emulated
  and with host graphics are kept apart.

`./emu verify` captures the display for each test, as for the graphics and
media workloads: the pages draw the same marker blocks, and a played stream
is paused on a frame for the capture (not in a measured run).

## Disk space and times

What the platform costs on a host, in disk space and in time, is kept in
[footprint.md](footprint.md), which says what each value is. Those
definitions are proposals until they are agreed; this is how the values of
the macOS host were taken on 2026-11-16, those of the Windows host on
2026-11-16 and 17 and those of the Linux host on 2026-11-17 and again on
2026-11-18 and 19, and how another
host's can be. The
rules for every measurement hold here too: a quiet host, and a value that was
not measured on the host reads "not measured".

- **Performance evaluation, time.** Not measured again: every recorded run
  has its duration, and `python3 evaluation/footprint.py times` adds them up
  per host and mode.
- **Target, disk space.** `python3 evaluation/footprint.py sizes`, on the
  host, once its targets are built.
- **Host installation.** On a host that the setup script has set up and that
  has its record:

  1. Remove the installation: `./setup.sh --uninstall` (`setup.cmd
     -Uninstall`). Then remove the downloads its tools kept, so that the
     installation has to fetch them again (on macOS the folders `Homebrew`,
     `colima` and `pip` in `~/Library/Caches`; on Windows
     `%LOCALAPPDATA%\pip\Cache`, and what is left of
     `~\.local\share\containers`, where Podman keeps the download of its
     machine image). On a Windows host whose record does not list QEMU and
     Podman, because it was set up before the record was kept, remove those
     two as well, or the setup does not install them:
     `winget uninstall SoftwareFreedomConservancy.QEMU` and
     `winget uninstall RedHat.Podman`. On a Linux host the kept downloads
     are `~/.cache/pip` (move it aside and put it back afterwards, where
     other projects use it) and the package manager's (`sudo apt-get
     clean`). On a Linux host whose record does not list QEMU, remove its
     packages by name: the five that the script asks for (`qemu-system-x86
     qemu-system-arm qemu-utils qemu-user-static binfmt-support`) and those
     that came with them and that nothing else needs. Check with `apt-get
     -s remove` that naming them removes them and nothing else, and then
     remove them. Use no `autoremove`, which takes whatever else the host
     no longer needs, and leave the player's package (`pulseaudio-utils`)
     where removing it takes the sound server along. A container engine
     that was on the host before the setup stays.
  2. Note the used space on the volume (`df -k`).
  3. Run the setup script with `--yes` (`-Yes`) and time it from its start to
     its end. Since 2026-11-17 the script sets a host up for the simulated
     ARM targets only with `--arm-targets` (`-ArmTargets`); a host of the
     evaluation has them, so give that option as well and say so with the
     value. The values taken until then are of a script that installed what
     those targets need without the option; a setup without it is not
     measured. On macOS Homebrew's installer asks for an administrator's
     password: give it beforehand (`sudo -v`, once more after the removal,
     which makes `sudo` forget it) and set `NONINTERACTIVE=1`, and the time
     has no waiting for a person in it. On Windows the installers of QEMU
     and of Podman each ask for elevation, which cannot be given beforehand:
     someone has to be at the host to answer at once, and the value says
     that the two prompts are in it.
  4. Take the size of every place the installation uses (`du -sk`) and the
     used space on the volume again. On macOS the places are `/opt/homebrew`,
     `~/.colima`, `~/.docker`, the three cache folders and `build/host/gui`.
     On Windows they are `C:\Program Files\qemu`,
     `C:\Program Files\RedHat\Podman`, `~\.local\share\containers` (Podman's
     machine: its disk `ext4.vhdx`, the machine image and the kept download),
     `%LOCALAPPDATA%\pip\Cache` and `build\host\gui`, each as the sizes of
     its files added (`Get-ChildItem -Recurse -Force -File | Measure-Object
     Length -Sum`), and the volume's used space from `Get-PSDrive C`. On
     Linux with apt they are the files of the installed packages (`dpkg -L`
     of each, the regular files given to `du -ck`), `build/host/gui`,
     `~/.cache/pip`, `/var/cache/apt/archives`, and for the engine
     `/var/lib/docker` (`sudo du -sk`), of which only the growth counts
     where the engine holds other things.
  5. Name what the removal left in place and the installation therefore did
     not install (on macOS the Xcode Command Line Tools; on Windows Python,
     WSL 2, the Windows Hypervisor Platform and winget; on the Linux host
     Docker, Python, the sound server's player and the libraries Qt loads).

- **Target, build time.** For each target of the host: empty the container
  engine of every image but the ones the setup script brought, and of its
  whole build cache (`docker image rm`, `docker builder prune --all --force`;
  the same with `podman`), then time `./emu build` with `--rebuild` for that
  target alone. The build's output must show no step marked `CACHED`.

      ./emu build --mode container --rebuild
      ./emu build --mode vm --arch arm64 --rebuild
      ./emu build --mode vm --arch arm32 --rebuild

  (and `--arch native` where the host's own architecture is not ARM64). This
  removes every image the engine holds: only for an engine that holds nothing
  else. On the Linux host, whose engine holds its owner's images too, only
  the project's were removed (`emu-target-debian`, the untagged images its
  builds left, the `debian` base image) and the whole build cache; no build
  of the project uses the others.
- **The installation with its targets, and all targets in one go.** In a new
  container engine (on macOS: `colima delete --force --data`, then
  `./setup.sh --yes` creates the virtual machine again), build the host's
  targets one after the other, timed, and take the sizes of step 4 again.
  The value must come from an engine that was never emptied: where the
  engine keeps its storage in a disk image, as Colima does, that file does
  not shrink when images are removed. On Linux, where Docker keeps its
  storage in a directory, an emptied engine serves.
- **On Windows, a new engine before every build, and room on the volume.**
  Podman's machine keeps its storage in a disk file that only grows, and a
  build in an emptied engine does not use the freed space first. So make the
  machine anew before each timed build (`podman machine rm --force`, then
  `setup.cmd -Yes`), and have more free on the volume than the 27 to 34 GB
  of 2026-11-16: with those, the builds of the host-native VM image and of
  the ARM64 VM image filled the volume at their last step, and all four
  targets in one engine could not be tried. How much is enough was not
  found. A machine that a full volume
  has broken is removed with `wsl --unregister podman-machine-default`
  followed by `podman machine rm --force`.
- **Afterwards** run `./emu verify`: the installation that was measured has
  to be one that works. On the macOS host all 124 checks came out as they
  had before the removal, and on the Linux host (on 2026-11-19, of 140
  checks there, one more failed in the complete run and passed when run
  again). On the Windows host 122 did; of the other two, one
  failed once and passed when run again, and one passed that had failed
  before ([footprint.md](footprint.md#windows-x86-64)).
