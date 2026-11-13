"""Launch one workload on the target OS and collect what it reports."""
import datetime
import json
import os
import shutil
import subprocess
import sys
import threading
import time

from . import catalog, container, drivers as driver_features, graphics, host, image, vm
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
}
KNOWN_OPTIONS.update(driver_features.AUDIO_OPTIONS)


class RunOptions:
    def __init__(self, mode, workload="prompt", args=(), arch="native", cpus=DEFAULT_CPUS,
                 memory_mb=DEFAULT_MEMORY_MB, drivers=None, options=None, extra_args=(), timeout=None,
                 echo=True, stdin_script=None, quiet_build=False, rebuild=False, resolution=None, graphics=None,
                 screenshot_dir=None, screenshot_format="png", window=False, muted=False, on_audio=None):
        self.mode = mode
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
        self.window = window                    # show a VM's display in a window
        self.muted = muted                      # start with the emulator's audio muted
        self.on_audio = on_audio                # called with the audio host process's details once it runs


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

    @property
    def ok(self):
        if self.attached:
            return self.process_exit == 0
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


def _display_plan(opts, probe, window=None):
    """The display this run gives the target, or None when it has none. A
    display is attached for workloads that use one, and whenever a resolution,
    a graphics provider or a window is asked for. `window` names the emulator's
    display backend that shows it in one."""
    declared = catalog.workload(opts.workload) or {}
    if not (declared.get("display") or opts.resolution or opts.graphics or opts.screenshot_dir or window):
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


def launch(opts):
    """Run a workload; returns an Outcome. Raises EmuError when the emulator
    cannot be started at all."""
    for name in opts.options:
        if name not in KNOWN_OPTIONS:
            raise EmuError("unknown --option %r (known: %s)" % (name, ", ".join(sorted(KNOWN_OPTIONS))))
    if opts.workload != "prompt" and opts.stdin_script is not None:
        raise EmuError("only the prompt workload reads input")

    outcome = Outcome()
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
    plan = None
    screens = None
    capturer = None
    capture_directory = None
    console = None
    try:
        if opts.mode == "container":
            if opts.arch != "native":
                raise EmuError("container mode runs the host's CPU architecture; --arch applies to VM mode")
            if opts.window:
                raise EmuError("--window shows the display of a VM; in container mode the target renders to an "
                               "output that is not shown anywhere", hint="add --mode vm")
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
                                                                           manifest["platform"]))
            display_args = []
            if display:
                env["EMU_DISPLAY"] = "%dx%d" % (display["width"], display["height"])
                env["EMU_GRAPHICS"] = display["provider"]
                if display["screen_hold"]:
                    env["EMU_SCREEN_HOLD"] = str(display["screen_hold"])
                    screens = graphics.Screens(opts.screenshot_dir, outcome.run_id, "png",
                                               graphics.container_capture(runtime, name))
                display_args = graphics.container_arguments(display)
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
            manifest = image.ensure("vm", container.detect, guest, quiet=opts.quiet_build, rebuild=opts.rebuild)
            data_disk = run_dir / "data.img"
            with open(data_disk, "wb") as handle:
                handle.truncate(int(opts.options.get("data-disk-mb", DEFAULT_DATA_DISK_MB)) * 1024 * 1024)
            plan = driver_features.plan_vm(opts.drivers, str(run_dir), opts.options, opts.muted)
            terminal = None
            if attached:
                size = shutil.get_terminal_size()
                name = os.environ.get("TERM", "")
                terminal = (name if name.replace("-", "").isalnum() else "vt100", size.columns, size.lines)
            qemu = host.require_tool(vm.QEMU_BINARY[guest], "VM mode with a %s guest" % guest)
            window = graphics.window_backend(qemu) if opts.window else None
            display = _display_plan(opts, lambda: graphics.probe_vm(qemu, window), window)
            display_args, display_backend, display_device = [], "none", None
            if display:
                display_args, display_backend, display_device = graphics.vm_arguments(
                    display, display["width"], display["height"], opts.memory_mb, opts.options)
                if display["screen_hold"]:
                    capture_args, capturer, capture_directory = graphics.capture_endpoint(display)
                    display_args += capture_args
                    screens = graphics.Screens(opts.screenshot_dir, outcome.run_id, opts.screenshot_format,
                                               lambda path: capturer.capture(path, opts.screenshot_format))
            cmdline = vm.kernel_command_line(guest, opts.workload, opts.args, opts.drivers,
                                             _flag(opts.options, "verbose-boot"), terminal, display,
                                             plan.kernel_settings)
            if interactive and not attached and host.host_os() == "windows":
                console = vm.Console()
            command, binary = vm.run_command(
                resolved, image.artifact_dir("vm", guest), data_disk, cmdline, opts.cpus, opts.memory_mb,
                attached, display_args + plan.qemu_args + opts.extra_args, opts.options, display_backend, console)
            emulator = {"mode": "vm", "variant": resolved["variant"], "guest_arch": guest,
                        "accelerator": resolved["accelerator"], "cpu_model": resolved["cpu_model"],
                        "machine": resolved["machine"], "runtime": vm.qemu_version(binary)}
            if display:
                emulator.update(_display_record(display, display_device))
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
            shown = " in a window" if emulator["display"].get("window") else ""
            outcome.notes.append("display %s%s, graphics %s (%s)" % (
                emulator["display"]["resolution"], shown, emulator["graphics"]["provider"],
                emulator["graphics"]["reason"]))
        if opts.echo:
            for note in outcome.notes:
                print("emu: " + note, file=sys.stderr, flush=True)

        if attached:
            outcome.attached = True
            outcome.started_at = time.time()
            outcome.process_exit = subprocess.call(command, env=host.tool_env())
            outcome.duration_seconds = time.time() - outcome.started_at
        else:
            _capture(command, opts, outcome, interactive, None if attached else screens, console)
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


def _capture(command, opts, outcome, interactive, screens=None, console=None):
    """Run the emulator and take in what it and the target print. The target's
    console is on the emulator's standard streams, or on `console`."""
    stdin = subprocess.PIPE if interactive and not console else subprocess.DEVNULL
    outcome.started_at = time.time()
    process = subprocess.Popen(command, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=host.tool_env())
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
