"""Launch one workload on the target OS and collect what it reports."""
import datetime
import json
import os
import shutil
import subprocess
import sys
import threading
import time

from . import armtargets, catalog, container, drivers as driver_features, graphics, host, image, redrat, rootfs, \
    vm, window
from .errors import EmuError
from .paths import BUILD_DIR

DEFAULT_CPUS = 4
DEFAULT_MEMORY_MB = 2048
DEFAULT_DATA_DISK_MB = 1024
KNOWN_OPTIONS = {
    "accel": "VM accelerator: hvf, kvm, whpx or tcg (default: the host's hypervisor for native, tcg otherwise)",
    "cpu": "VM CPU model (default: the host's own for native, cortex-a53 for arm64, cortex-a15 for arm32)",
    "disk-cache": "QEMU cache mode of the data disk, such as none or writeback (default: QEMU's default)",
    "data-disk-mb": "size of the VM's /data scratch disk in MiB (default: %d)" % DEFAULT_DATA_DISK_MB,
    "verbose-boot": "show kernel boot messages in VM mode (yes/no, default: no)",
    "host-address": "container mode: name or address containers use to reach the host",
    "host-bind": "container mode: address host-side processes listen on",
    "venus": "VM mode with host graphics: map Vulkan to the host GPU too (yes/no, default: when QEMU offers it on Linux)",
    "window": "VM mode with a window: qemu shows the display in QEMU's own window, which has no toolbar and takes "
              "no remote control keys (default: the launcher's window wherever it can show the display)",
    rootfs.RDKE_DIR_OPTION: "--rootfs rdke: the directory with the RDK-E image's kernel and root file system "
                            "(default: build/rdke/arm64)",
}
KNOWN_OPTIONS.update(driver_features.AUDIO_OPTIONS)


class RunOptions:
    def __init__(self, mode, workload="prompt", args=(), arch="native", cpus=DEFAULT_CPUS,
                 memory_mb=DEFAULT_MEMORY_MB, drivers=None, options=None, extra_args=(), timeout=None,
                 echo=True, stdin_script=None, quiet_build=False, rebuild=False, resolution=None, graphics=None,
                 screenshot_dir=None, screenshot_format="png", window=False, muted=False, on_audio=None,
                 fullscreen=False, on_line=None, on_viewer=None,
                 redrat_profile=None, redrat_device=None, rootfs=rootfs.DEFAULT):
        self.mode = mode
        self.rootfs = rootfs                    # the root file system the target starts from (emulator/rootfs.py)
        self.workload = workload
        self.args = list(args)
        self.arch = arch
        self.cpus = cpus
        self.memory_mb = memory_mb
        self.drivers = driver_features.parse([]) if drivers is None else drivers
        self.options = dict(options or {})
        self.extra_args = list(extra_args)      # passed through to qemu or the container runtime
        self.timeout = timeout
        self.echo = echo
        self.stdin_script = stdin_script        # bytes typed into the workload, for automated runs
        self.quiet_build = quiet_build
        self.rebuild = rebuild
        self.resolution = resolution            # display resolution: 720p, 1080p or 4k
        self.graphics = graphics                # auto, host or emulated
        self.screenshot_dir = screenshot_dir    # capture the display here when a workload shows a finished frame
        self.screenshot_format = screenshot_format
        self.window = window                    # show the display in a window
        self.fullscreen = fullscreen            # ... that starts full screen
        self.redrat_profile = redrat_profile
        self.redrat_device = redrat_device
        self.muted = muted                      # start with the emulator's audio muted
        self.on_audio = on_audio                # called with the audio host process's details once it runs
        self.on_line = on_line                  # called with each line of the target's console
        # Called with the display window (window.Viewer) once it runs; the
        # window then takes commands, for a check that drives it.
        self.on_viewer = on_viewer


class Outcome:
    def __init__(self):
        self.run_id = None
        self.command = []
        self.environment = {}
        self.ready = None               # what the target reported when it came up
        self.boot_seconds = None
        self.workload = None            # the workload's own id and version
        self.drivers = []               # driver providers the target started
        self.results = []
        self.exit_code = None           # the workload's exit status inside the target
        self.process_exit = None        # exit status of the emulator process
        self.timed_out = False
        self.protocol_errors = []
        self.host_traces = {}
        self.screens = []               # display captures, one per frame a workload announced
        self.notes = []
        self.output = []                # captured console lines
        self.started_at = None
        self.duration_seconds = None
        self.attached = False           # ran attached to the terminal, nothing captured
        self.window_closed = False      # the display window was closed, which ended the emulator

    @property
    def ok(self):
        if self.attached:
            return self.process_exit == 0 or self.window_closed
        return self.exit_code == 0 and not self.timed_out


def _run_id():
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "%s-%s" % (stamp, os.urandom(3).hex())


def _flag(options, name):
    return str(options.get(name, "no")).lower() in ("1", "yes", "true", "on")


def _image_identity(manifest, kind):
    identity = {
        "name": manifest["name"],
        "version": manifest["version"],
        "kind": kind,
        "arch": manifest["arch"],
        "source": manifest["source"],
        "definition_sha256": manifest["definition_sha256"],
        "build_revision": manifest.get("build_revision"),
        "built_at": manifest.get("built_at"),
    }
    if kind == "vm":
        identity["kernel_release"] = manifest.get("kernel_release")
        identity["rootfs_sha256"] = manifest["files"]["rootfs.img"]["sha256"]
    else:
        identity["image_id"] = manifest.get("image_id")
    return identity


def _display_plan(opts, probe, window=None, always=False):
    """The display this run gives the target, or None when it has none. A
    display is attached for workloads that use one, and whenever a resolution,
    a graphics provider or a window is asked for; `always` is for a target
    whose own software uses one. `window` names the emulator's display backend
    that shows it in one."""
    declared = catalog.workload(opts.workload) or {}
    if not (always or declared.get("display") or opts.resolution or opts.graphics or opts.screenshot_dir or window):
        return None
    width, height = graphics.resolution(opts.resolution)
    plan = graphics.choose(opts.graphics, probe)
    plan.update({"width": width, "height": height, "window": window,
                 "screen_hold": graphics.SCREEN_HOLD_SECONDS if opts.screenshot_dir else 0})
    return plan


def _display_record(plan, device):
    display = {"resolution": "%dx%d" % (plan["width"], plan["height"])}
    if plan.get("window"):
        display["window"] = plan["window"]
    return {"display": display,
            "graphics": {"requested": plan["requested"], "provider": plan["provider"], "reason": plan["reason"],
                         "device": device}}


def _require_rdke(opts):
    """What a run from the RDK-E root file system cannot have: everything that
    the Debian root file system's own software provides."""
    refused = None
    if opts.mode != "vm":
        refused = ("the RDK-E root file system runs in VM mode only: there is no container image of it",
                   "add --mode vm")
    elif opts.workload != "prompt":
        refused = ("the workloads are part of the Debian root file system; from the RDK-E one the target starts "
                   "its own software", "leave out --workload")
    elif opts.args:
        refused = ("workload arguments are for the Debian root file system's workloads", None)
    elif dict(opts.drivers) != dict(driver_features.parse([])) or getattr(opts.drivers, "declined", None):
        refused = ("driver features are provided by services of the Debian root file system", "leave out --driver")
    elif opts.screenshot_dir:
        refused = ("captures are taken when a workload of the Debian root file system reports a finished frame",
                   "leave out --screenshot")
    elif opts.redrat_profile:
        refused = ("remote control keys do not reach a target started from the RDK-E root file system yet",
                   "leave out --redrat-profile")
    elif opts.rebuild:
        refused = ("the launcher does not build the RDK-E root file system", "%s says how it is built"
                   % rootfs.RDKE_README)
    elif opts.stdin_script is not None:
        refused = ("a scripted prompt needs the Debian root file system", None)
    if refused:
        raise EmuError(refused[0], hint=refused[1])


def launch(opts):
    """Run a workload; returns an Outcome. Raises EmuError when the emulator
    cannot be started at all."""
    if opts.rootfs not in rootfs.CHOICES:
        raise EmuError("unknown root file system %r (known: %s)" % (opts.rootfs, ", ".join(rootfs.CHOICES)))
    rdke = opts.rootfs == rootfs.RDKE
    if rdke:
        _require_rdke(opts)
        opts.drivers = driver_features.Chosen()     # no driver feature: the target has none of their services
    for name in opts.options:
        if name not in KNOWN_OPTIONS:
            raise EmuError("unknown --option %r (known: %s)" % (name, ", ".join(sorted(KNOWN_OPTIONS))))
    if opts.workload != "prompt" and opts.stdin_script is not None:
        raise EmuError("only the prompt workload reads input")
    if opts.redrat_device and not opts.redrat_profile:
        raise EmuError("--redrat-device requires --redrat-profile")
    if opts.redrat_profile:
        receiver = redrat.select_device(opts.redrat_device)
        opts.redrat_device = receiver["id"]
        profile = redrat.load_profile(opts.redrat_profile)
        redrat.validate_signals(profile["buttons"])
    # Full screen is a state of the window, and remote control keys are typed
    # into it or clicked beside it.
    shown = bool(opts.window or opts.fullscreen or opts.redrat_profile)
    notes = []
    # A launcher display window provides the joined keyboard and on-screen
    # remote inputs; workloads used through their display get one automatically.
    keyed = bool(shown or (catalog.workload(opts.workload) or {}).get("window"))
    if not shown and (catalog.workload(opts.workload) or {}).get("window"):
        # A workload that is used through its display, with remote control
        # keys: it gets the window without being asked, where there is one.
        if window.gui_python():
            shown = True
            notes.append("the %s workload is used through its display, so it is shown in a window, with remote "
                         "control keys from the keyboard" % opts.workload)
        else:
            notes.append("the %s workload is used through its display, which is not shown: Qt for Python (%s) is "
                         "not installed, so the launcher has no window" % (opts.workload, window.PACKAGE))

    outcome = Outcome()
    outcome.notes += notes
    outcome.run_id = _run_id()
    run_dir = BUILD_DIR / "run" / outcome.run_id
    run_dir.mkdir(parents=True)
    interactive = opts.workload == "prompt"
    # A workload that plays sound gets the audio feature unless the run says otherwise.
    drivers = driver_features.Chosen(opts.drivers)
    drivers.declined = set(getattr(opts.drivers, "declined", ()))
    for feature, strategy in driver_features.ON_DEMAND.items():
        if (catalog.workload(opts.workload) or {}).get(feature) and feature not in drivers \
                and feature not in drivers.declined:
            drivers[feature] = strategy
    opts.drivers = drivers
    # Attach straight to the terminal for a person; capture everything else.
    attached = interactive and opts.stdin_script is None and host.stdin_is_tty() and sys.stdout.isatty()
    on_terminal = attached
    # The RDK-E target reports nothing to the launcher: its console is the
    # launcher's own output, on a terminal or not.
    attached = attached or rdke
    plan = None
    screens = None
    capturer = None
    capture_directory = None
    console = None
    viewer = None
    viewer_plan = None      # what the display window is started with
    keys_first = False      # the launcher's window was chosen over QEMU's for remote control input
    stop_emulator = []      # ends the emulator when the display window is closed
    try:
        if shown:
            window.require_python("showing the display in a window")
        if opts.mode == "container":
            if opts.arch != "native":
                raise EmuError("container mode runs the host's CPU architecture; --arch applies to VM mode")
            runtime = container.detect()
            arch = host.host_arch()
            manifest = image.ensure("container", lambda: runtime, arch, quiet=opts.quiet_build, rebuild=opts.rebuild)
            plan = driver_features.plan_container(opts.drivers, runtime, str(run_dir), opts.options,
                                                  manifest["image_tag"], manifest["platform"], opts.muted)
            env = dict(plan.container_env)
            if opts.drivers:
                env["EMU_DRIVERS"] = ",".join("%s=%s" % item for item in sorted(opts.drivers.items()))
            name = "emu-" + outcome.run_id.lower()
            display = _display_plan(opts, lambda: graphics.probe_container(runtime, manifest["image_tag"],
                                                                           manifest["platform"]),
                                    graphics.LAUNCHER_WINDOW if shown else None)
            display_args = []
            if display:
                env["EMU_DISPLAY"] = "%dx%d" % (display["width"], display["height"])
                env["EMU_GRAPHICS"] = display["provider"]
                if shown:
                    # The target serves its display on a port of the container
                    # (emuscreen), published on this host for the window, and
                    # takes remote control keys from a program the window runs
                    # in the container.
                    port = window.free_port()
                    env["EMU_SCREEN_PORT"] = "5900"
                    env["EMU_REMOTE"] = "exec"
                    display_args += ["--publish", "127.0.0.1:%d:5900" % port]
                    viewer_plan = {"display": ("127.0.0.1", port),
                                   "keys_exec": [runtime.cli, "exec", "-i", name, "/opt/emu/remote", "stdin"]}
                    stop_emulator.append(lambda: runtime.run("kill", name, timeout=30))
                if display["screen_hold"]:
                    env["EMU_SCREEN_HOLD"] = str(display["screen_hold"])
                    screens = graphics.Screens(opts.screenshot_dir, outcome.run_id, "png",
                                               graphics.container_capture(runtime, name))
                display_args += graphics.container_arguments(display)
            command = container.run_command(
                runtime, manifest["image_tag"], manifest["platform"], opts.workload, opts.args, opts.cpus,
                opts.memory_mb, env, interactive, attached, display_args + opts.extra_args, name)
            emulator = {"mode": "container", "variant": "container", "guest_arch": arch,
                        "runtime": runtime.version(), "engine": runtime.engine_info()}
            if display:
                device = "the engine's GPU render node (/dev/dri)" if display["provider"] == "host" else \
                         "headless compositor output, rendering by the target CPU"
                emulator.update(_display_record(display, device))
            if (emulator["engine"].get("cpus") or 0) < opts.cpus:
                outcome.notes.append("the container engine has %s CPUs, fewer than the %d requested"
                                     % (emulator["engine"].get("cpus"), opts.cpus))
            elif not container.can_pin(emulator["engine"], opts.cpus):
                outcome.notes.append("the container engine cannot pin CPUs (rootless, without the cpuset controller): "
                                     "the target sees all %s CPUs and is limited to the CPU time of %d"
                                     % (emulator["engine"].get("cpus"), opts.cpus))
            image_identity = _image_identity(manifest, "container")
        elif opts.mode == "vm":
            resolved = vm.resolve(opts.arch, opts.options.get("accel"), opts.options.get("cpu"))
            outcome.notes += resolved["notes"]
            guest = resolved["guest_arch"]
            # Neither a build nor a VM for a simulated ARM target that this
            # host is not set up for.
            files = data_disk = manifest = None
            if rdke:
                if guest != rootfs.RDKE_ARCH:
                    raise EmuError("the RDK-E root file system is built for an ARM64 guest, and this run's guest "
                                   "is %s" % guest, hint="--arch arm64 runs it on a simulated CPU")
                files = rootfs.rdke_files(opts.options)
            else:
                armtargets.require(guest, container.detect)
                manifest = image.ensure("vm", container.detect, guest, quiet=opts.quiet_build, rebuild=opts.rebuild)
                data_disk = run_dir / "data.img"
                with open(data_disk, "wb") as handle:
                    handle.truncate(int(opts.options.get("data-disk-mb", DEFAULT_DATA_DISK_MB)) * 1024 * 1024)
            qemu = host.require_tool(vm.QEMU_BINARY[guest], "VM mode with a %s guest" % guest)
            virtio_sound = True
            if opts.drivers.get("audio") in ("emulated", "host"):
                virtio_sound = vm.has_device(qemu, "virtio-sound-pci")
                if not virtio_sound:
                    outcome.notes.append("this QEMU build has no virtio-sound-pci device; using the target's "
                                         "software ALSA device%s" % (
                                             " connected to the host audio process" if opts.drivers["audio"] == "host"
                                             else ""))
            plan = driver_features.plan_vm(opts.drivers, str(run_dir), opts.options, opts.muted, virtio_sound)
            terminal = None
            if on_terminal:
                size = shutil.get_terminal_size()
                name = os.environ.get("TERM", "")
                terminal = (name if name.replace("-", "").isalnum() else "vt100", size.columns, size.lines)
            # The launcher's own window, or QEMU's where only that one can
            # show a display rendered on the host GPU.
            kind = None
            if shown:
                kind = graphics.window_backend(qemu) if opts.options.get("window") == "qemu" else \
                    graphics.window_kind(qemu, opts.graphics)
                if kind != graphics.LAUNCHER_WINDOW and keyed and opts.options.get("window") != "qemu" \
                        and (opts.graphics or "auto") == "auto":
                    # The launcher window takes remote input, so prefer it
                    # when host graphics acceleration is not required.
                    kind = graphics.LAUNCHER_WINDOW
                    keys_first = True
            own = kind == graphics.LAUNCHER_WINDOW
            if kind and not own and opts.redrat_profile:
                asked = opts.options.get("window") == "qemu"
                raise EmuError("RedRat input needs the launcher's own window, and this run shows the "
                               "display in QEMU's (%s): %s" % (kind, "--option window=qemu asks for that" if asked
                                                               else "with host graphics acceleration this QEMU "
                                                                    "can show the display nowhere else"),
                               hint="leave out --option window=qemu" if asked else "add --graphics emulated")
            # RDK-E's own software draws its user interface: always a display.
            display = _display_plan(opts, lambda: graphics.probe_vm(qemu, None if own else kind), kind, always=rdke)
            display_args, display_backend, display_device = [], "none", None
            vnc = None
            if display:
                display_args, display_backend, display_device = graphics.vm_arguments(
                    display, display["width"], display["height"], opts.memory_mb, opts.options)
                if own:
                    # QEMU serves the display for the window, and the target
                    # fetches remote control keys from a port the window
                    # listens on (10.0.2.2 is this host, seen from the target).
                    vnc_args, vnc, vnc_directory = graphics.vnc_endpoint()
                    display_args += vnc_args
                    viewer_plan = {"display": vnc, "directory": vnc_directory}
                    if rdke:
                        outcome.notes.append("remote control keys do not reach a target started from the RDK-E root "
                                             "file system yet: nothing in it fetches them from the window")
                    else:
                        port = window.free_port()
                        plan.kernel_settings["remote"] = "10.0.2.2:%d" % port
                        viewer_plan["keys_listen"] = port
                elif kind and opts.fullscreen:
                    display_args.append("-full-screen")
                if display["screen_hold"]:
                    capture_args, capturer, capture_directory = graphics.capture_endpoint(display, vnc)
                    display_args += capture_args
                    screens = graphics.Screens(opts.screenshot_dir, outcome.run_id, opts.screenshot_format,
                                               lambda path: capturer.capture(path, opts.screenshot_format))
            if rdke:
                # Boot messages are shown unless the run says not to: the
                # target reports nothing else to the launcher.
                cmdline = vm.plain_command_line(guest, str(opts.options.get("verbose-boot", "yes")).lower()
                                                not in ("0", "no", "false", "off"))
                # A keyboard for QEMU's own window, which types into the guest.
                display_args += ["-device", "virtio-keyboard-pci"]
            else:
                cmdline = vm.kernel_command_line(guest, opts.workload, opts.args, opts.drivers,
                                                 _flag(opts.options, "verbose-boot"), terminal, display,
                                                 plan.kernel_settings)
            if interactive and not attached and host.host_os() == "windows":
                console = vm.Console()
            command, binary = vm.run_command(
                resolved, image.artifact_dir("vm", guest), data_disk, cmdline, opts.cpus, opts.memory_mb,
                on_terminal, display_args + plan.qemu_args + opts.extra_args, opts.options, display_backend, console,
                files)
            emulator = {"mode": "vm", "variant": resolved["variant"], "guest_arch": guest,
                        "accelerator": resolved["accelerator"], "cpu_model": resolved["cpu_model"],
                        "machine": resolved["machine"], "runtime": vm.qemu_version(binary)}
            if display:
                emulator.update(_display_record(display, display_device))
            if rdke:
                emulator["rootfs"] = rootfs.RDKE
                image_identity = {"name": rootfs.RDKE, "kind": "vm", "arch": guest,
                                  "files": {key: str(path) for key, path in files.items() if path}}
            else:
                image_identity = _image_identity(manifest, "vm")
        else:
            raise EmuError("unknown mode: %s" % opts.mode)

        emulator.update({"cpus": opts.cpus, "memory_mb": opts.memory_mb, "options": opts.options,
                         "extra_args": opts.extra_args})
        if opts.drivers.get("audio"):
            emulator["audio"] = {"strategy": opts.drivers["audio"]}
            if plan.audio:
                emulator["audio"].update({key: plan.audio.get(key) for key in ("player", "plays", "sink", "path")})
                # Where `emu audio` finds this emulator's mute switch.
                with open(run_dir / "audio.json", "w") as handle:
                    json.dump({"run_id": outcome.run_id, "pid": os.getpid(), "workload": opts.workload,
                               "control_port": plan.audio["control_port"]}, handle)
                outcome.notes.append("audio through the host OS (%s)%s" % (
                    plan.audio["source"], ", muted" if opts.muted else ""))
                if opts.on_audio:
                    opts.on_audio(dict(plan.audio))
        outcome.command = command
        outcome.environment = {"host": host.describe(), "emulator": emulator, "image": image_identity,
                               "drivers": dict(opts.drivers), "launcher_revision": image.git_revision()}
        if emulator.get("graphics"):
            where = {None: "", graphics.LAUNCHER_WINDOW: " in a window"}.get(
                emulator["display"].get("window"), " in QEMU's own window (no toolbar, no remote control keys)")
            outcome.notes.append("display %s%s, graphics %s (%s)" % (
                emulator["display"]["resolution"], where, emulator["graphics"]["provider"],
                emulator["graphics"]["reason"]))
        if viewer_plan:
            emulator["display"]["input_sources"] = ["keyboard", "on-screen"]
            if opts.redrat_profile:
                emulator["display"]["input_sources"].append("redrat")
                emulator["display"].update(redrat_profile=opts.redrat_profile, redrat_device=opts.redrat_device)
            if keys_first:
                outcome.notes.append("%s, so the display is in the launcher's window; QEMU's own window would "
                                     "show it rendered on the host GPU and take no remote control keys (--graphics "
                                     "host asks for that)" % (
                                         "remote control input was requested" if opts.redrat_profile else
                                         "the %s workload is operated with remote control keys" % opts.workload))
        if opts.echo:
            for note in outcome.notes:
                print("emu: " + note, file=sys.stderr, flush=True)

        if viewer_plan:
            viewer = window.start_viewer(
                viewer_plan["display"], "Emulator: %s, %s" % (opts.workload, emulator["variant"]),
                fullscreen=opts.fullscreen,
                keys_exec=viewer_plan.get("keys_exec"), keys_listen=viewer_plan.get("keys_listen"),
                redrat_profile=opts.redrat_profile, redrat_device=opts.redrat_device,
                audio_port=plan.audio["control_port"] if plan.audio else None, control=bool(opts.on_viewer),
                # A VM's display server can serve less than the display (QEMU 8.2: 2560x2048).
                expect=(display["width"], display["height"]) if opts.mode == "vm" and display else None)
            if opts.on_viewer:
                opts.on_viewer(viewer)

        def started(process):
            """Closing the display window ends the emulator."""
            if not viewer:
                return

            def watch():
                viewer.process.wait()
                if process.poll() is None:
                    outcome.window_closed = True
                    for stop in stop_emulator:
                        try:
                            stop()
                        except (OSError, subprocess.SubprocessError):
                            pass
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()

            threading.Thread(target=watch, daemon=True).start()

        if attached:
            outcome.attached = True
            outcome.started_at = time.time()
            # Off a terminal too, what is typed or piped into the launcher
            # goes to the target's console.
            process = subprocess.Popen(command, env=host.tool_env())
            started(process)

            def on_timeout():
                outcome.timed_out = True
                process.kill()

            # Only a target that reports nothing is stopped by the clock here:
            # a person at the Debian prompt ends it themself.
            watchdog = threading.Timer(opts.timeout, on_timeout) if opts.timeout and rdke else None
            if watchdog:
                watchdog.start()
            try:
                outcome.process_exit = process.wait()
            except KeyboardInterrupt:
                process.kill()
                raise
            finally:
                if watchdog:
                    watchdog.cancel()
            outcome.duration_seconds = time.time() - outcome.started_at
        else:
            _capture(command, opts, outcome, interactive, None if attached else screens, console, started)
        if viewer and viewer.process.poll() not in (None, 0):
            errors = viewer.errors()
            raise EmuError("the display window failed (exit %s)%s" %
                           (viewer.process.returncode, ": " + errors if errors else ""))
        if screens:
            outcome.screens = screens.captures
        for process in plan.host_processes:
            if process.get("trace") and os.path.exists(process["trace"]):
                with open(process["trace"]) as handle:
                    outcome.host_traces[process["feature"]] = handle.read()
        outcome.environment["host_processes"] = [
            {key: value for key, value in process.items() if key != "trace"} for process in plan.host_processes]
        return outcome
    finally:
        if viewer:
            viewer.close()
        if viewer_plan:
            graphics.remove_directory(viewer_plan.get("directory"))
        if plan:
            plan.stop()
        if capturer:
            capturer.close()
        if console:
            console.close()
        graphics.remove_directory(capture_directory)
        shutil.rmtree(run_dir, ignore_errors=True)


def _forward_input(process, sink, source, ready, end_with_eot):
    """Copy input to the target, through `sink`, once the target is up."""
    ready.wait(timeout=300)
    time.sleep(0.5)
    try:
        if isinstance(source, bytes):
            sink.write(source)
            sink.flush()
        else:
            while True:
                chunk = source.read1(4096) if hasattr(source, "read1") else source.read(4096)
                if not chunk:
                    break
                sink.write(chunk)
                sink.flush()
        if end_with_eot:
            # A serial console has no end-of-file; Ctrl-D tells the shell.
            sink.write(b"\x04")
            sink.flush()
            process.wait()
        sink.close()
    except (OSError, ValueError):
        pass


def _capture(command, opts, outcome, interactive, screens=None, console=None, started=None):
    """Run the emulator and take in what it and the target print. The target's
    console is on the emulator's standard streams, or on `console`. `started`
    is called with the emulator's process once it runs."""
    stdin = subprocess.PIPE if interactive and not console else subprocess.DEVNULL
    outcome.started_at = time.time()
    process = subprocess.Popen(command, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=host.tool_env())
    if started:
        started(process)
    ready = threading.Event()
    lock = threading.Lock()

    def take(stream):
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                with lock:
                    outcome.output.append(line)
                    if opts.echo:
                        print(line, flush=True)
                    _parse(line, outcome, ready, screens)
                    if opts.on_line:
                        opts.on_line(line)
                    if opts.mode == "vm" and any(text in line for text in vm.GAVE_UP):
                        outcome.notes.append("the hypervisor stopped running the target; the emulator was ended")
                        process.kill()
        except OSError:
            pass    # the emulator closed the console's connection as it ended

    def on_timeout():
        outcome.timed_out = True
        process.kill()

    watchdog = threading.Timer(opts.timeout, on_timeout) if opts.timeout else None
    if watchdog:
        watchdog.start()
    console_reader = None
    try:
        sink = process.stdin
        connection = console.accept(process) if console else None
        if connection:
            sink = connection.makefile("wb", buffering=0)
            console_reader = threading.Thread(target=take, args=(connection.makefile("rb"),), daemon=True)
            console_reader.start()
        if interactive and sink:
            source = opts.stdin_script if opts.stdin_script is not None else sys.stdin.buffer
            threading.Thread(target=_forward_input, args=(process, sink, source, ready, opts.mode == "vm"),
                             daemon=True).start()
        take(process.stdout)
    except KeyboardInterrupt:
        process.kill()
        raise
    finally:
        outcome.process_exit = process.wait()
        if watchdog:
            watchdog.cancel()
        if console_reader:
            console_reader.join(timeout=5)
        ready.set()
        process.stdout.close()
        outcome.duration_seconds = time.time() - outcome.started_at


def _parse(line, outcome, ready, screens=None):
    # A console line can carry a prompt or kernel text in front of the marker.
    start = line.find("EMU-")
    if start < 0:
        return
    marker, separator, payload = line[start:].partition(": ")
    if not separator:
        return
    if marker == "EMU-EXIT":
        try:
            outcome.exit_code = int(payload.strip())
        except ValueError:
            outcome.protocol_errors.append(line)
        return
    if marker not in ("EMU-READY", "EMU-DRIVER", "EMU-WORKLOAD", "EMU-RESULT", "EMU-SCREEN"):
        return
    try:
        data = json.loads(payload)
    except ValueError:
        outcome.protocol_errors.append(line)
        return
    if marker == "EMU-READY":
        outcome.ready = data
        outcome.boot_seconds = round(time.time() - outcome.started_at, 3)
        ready.set()
    elif marker == "EMU-DRIVER":
        outcome.drivers.append(data)
    elif marker == "EMU-WORKLOAD":
        outcome.workload = data
    elif marker == "EMU-SCREEN":
        # The workload holds this frame on the display while it is captured.
        if screens:
            screens.on_marker(data)
    else:
        outcome.results.append(data)
