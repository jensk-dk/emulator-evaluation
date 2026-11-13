"""Driver-feature strategies.

A driver feature is something target software gets from a target OS driver,
reached through that driver's interface (a device node, for instance). Each
feature can be provided in three ways, in both execution modes:

  emulated  the driver's behaviour is emulated inside the emulator
  mocked    a stub stands in for the driver and returns canned data
  host      a host-side process reroutes the feature to the host OS

The target-side half of each feature lives in target/rootfs/opt/emu/drivers/.
This module is the host-side half: what to add to the emulator's command line
and which host-side processes to run.
"""
import json
import os
import subprocess
import sys

from . import host, relay
from .errors import EmuError
from .paths import ROOT

STRATEGIES = ("emulated", "mocked", "host")
FEATURES = {
    "hwrng": "hardware random number generator, read by target software from /dev/hwrng",
    "audio": "sound output, played by target software on the ALSA device \"default\"",
}
# Features every run has unless it says otherwise, with their strategy.
DEFAULTS = {"hwrng": "emulated"}
# Features a run has when its workload uses them (evaluation/workloads.json)
# or it asks for them. Sound goes to the host: that is where it can be heard.
ON_DEMAND = {"audio": "host"}
AUDIO_OPTIONS = {
    "audio-sink": "audio with the host strategy: the host output device to play on (default: the host's default)",
    "audio-output": "audio with the host strategy: \"none\" takes the sound in without playing it on the host",
}


class Chosen(dict):
    """{feature: strategy}; `declined` names the features turned off with
    FEATURE=none, so that a workload's needs do not turn them on again."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.declined = set()


def parse(specs):
    """Turn ["hwrng=mocked", ...] into {"hwrng": "mocked"}, applying defaults.
    The strategy "none" leaves a feature out."""
    chosen = Chosen(DEFAULTS)
    for spec in specs or []:
        feature, separator, strategy = spec.partition("=")
        if not separator or feature not in FEATURES:
            raise EmuError("bad --driver %r: expected FEATURE=STRATEGY with FEATURE one of: %s"
                           % (spec, ", ".join(sorted(FEATURES))))
        if strategy == "none":
            chosen.pop(feature, None)
            chosen.declined.add(feature)
        elif strategy in STRATEGIES:
            chosen[feature] = strategy
        else:
            raise EmuError("bad --driver %r: STRATEGY must be one of: %s, none" % (spec, ", ".join(STRATEGIES)))
    return chosen


class Plan:
    """What a run needs on the host for its driver features."""

    def __init__(self):
        self.qemu_args = []
        self.container_env = {}
        self.kernel_settings = {}   # VM mode: emu.NAME=VALUE for the target's kernel command line
        self.host_processes = []    # dicts describing running host-side processes
        self.audio = None           # the audio feature's host-side process, when the run has one
        self._children = []
        self._relays = []

    def start_host_process(self, feature, bind, trace_path, extra=()):
        command = [sys.executable, "-m", "emulator.hostd", feature, "--bind", bind] + list(extra)
        if trace_path:
            command += ["--trace", str(trace_path)]
        child = subprocess.Popen(command, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 env=host.tool_env({"PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}))
        self._children.append(child)
        line = child.stdout.readline().decode(errors="replace")
        try:
            info = json.loads(line)
        except ValueError:
            info = {"error": "no startup message from the host-side process"}
        if "error" in info:
            self.stop()
            raise EmuError("host-side process for %s failed to start: %s" % (feature, info["error"]))
        info["trace"] = str(trace_path) if trace_path else None
        self.host_processes.append(info)
        return info

    def start_relay(self, runtime, image_tag, platform, run_dir, port):
        """Give containers a way to the host-side process on `port` where the
        engine has none; returns the port they reach it on."""
        name = "emu-relay-%s-%d" % (os.path.basename(run_dir).lower(), port)
        try:
            self._relays.append(relay.Relay(runtime, image_tag, platform, name, ("127.0.0.1", port),
                                            host.tool_env(), os.path.join(run_dir, name + ".log")))
        except (OSError, RuntimeError) as error:
            self.stop()
            raise EmuError("the relay to the host-side process failed to start: %s" % error)
        return self._relays[-1].port

    def stop(self):
        for item in self._relays:
            item.stop()
        self._relays = []
        for child in self._children:
            if child.poll() is None:
                child.terminate()
        for child in self._children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
            if child.stdout:
                child.stdout.close()
        self._children = []


def _audio_arguments(options, muted):
    extra = []
    if options.get("audio-sink"):
        extra += ["--sink", options["audio-sink"]]
    if str(options.get("audio-output", "")).lower() == "none":
        extra += ["--player", "none"]
    if muted:
        extra.append("--muted")
    return extra


def _start_audio(plan, bind, run_dir, options, muted, extra=()):
    info = plan.start_host_process("audio", bind, os.path.join(run_dir, "audio-host.trace"),
                                   _audio_arguments(options, muted) + list(extra))
    plan.audio = info
    return info


def plan_vm(drivers, run_dir, options=None, muted=False):
    plan = Plan()
    options = options or {}
    audio = drivers.get("audio")
    if audio in ("emulated", "host"):
        # An emulated sound card; the target kernel's virtio-sound driver makes
        # it an ALSA card. QEMU keeps the card's time whatever its backend is.
        backend = "none,id=emu-audio"
        if audio == "host" and hasattr(os, "mkfifo"):
            # The card's backend is the host-side process: QEMU writes the
            # samples, as a WAV stream, into a named pipe that process reads.
            pipe = os.path.join(run_dir, "audio.pipe")
            _start_audio(plan, "127.0.0.1", run_dir, options, muted, ["--pipe", pipe])
            backend = "wav,id=emu-audio,path=%s,out.frequency=48000,out.channels=2,out.format=s16" \
                      % str(pipe).replace(",", ",,")
            plan.audio["path"] = "the emulated sound card's backend, through a named pipe"
        elif audio == "host":
            # No named pipes on this host: the target gets no sound card, and
            # its shim device sends the samples through QEMU's network, which
            # reaches the host's loopback address at 10.0.2.2.
            info = _start_audio(plan, "127.0.0.1", run_dir, options, muted)
            plan.kernel_settings["audiohost"] = "10.0.2.2:%d" % info["port"]
            plan.audio["path"] = "the target's shim device, through the emulator's network"
        if "audiohost" not in plan.kernel_settings:
            plan.qemu_args += ["-audiodev", backend, "-device", "virtio-sound-pci,audiodev=emu-audio"]
    # mocked: no sound card; the stub device inside the target takes the samples.
    strategy = drivers.get("hwrng")
    if strategy == "emulated":
        # An emulated virtio RNG device fed by QEMU's own generator; the
        # target kernel's virtio-rng driver exposes it as /dev/hwrng.
        plan.qemu_args += ["-object", "rng-builtin,id=hwrng0", "-device", "virtio-rng-pci,rng=hwrng0"]
    elif strategy == "host":
        # The same device, but its data comes from a host-side process.
        info = plan.start_host_process("hwrng", "127.0.0.1", os.path.join(run_dir, "hwrng-host.trace"))
        plan.qemu_args += ["-chardev", "socket,id=hwrng-host,host=127.0.0.1,port=%d" % info["port"],
                           "-object", "rng-egd,id=hwrng0,chardev=hwrng-host",
                           "-device", "virtio-rng-pci,rng=hwrng0"]
    # mocked: no device at all; the stub inside the target provides /dev/hwrng.
    return plan


def _container_bind_address(runtime):
    """Address the host-side process listens on so containers can reach it.

    Where the engine runs in a VM (macOS, Windows) it forwards the host's
    loopback. A native Linux engine reaches the host through its bridge."""
    if host.host_os() != "linux":
        return "127.0.0.1"
    if runtime.name == "docker":
        done = runtime.run("network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}")
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    return "0.0.0.0"


def plan_container(drivers, runtime, run_dir, options, image_tag, platform, muted=False):
    plan = Plan()
    if drivers.get("audio") == "host":
        bind = options.get("host-bind") or _container_bind_address(runtime)
        info = _start_audio(plan, bind, run_dir, options, muted)
        port = info["port"]
        if not (options.get("host-bind") or options.get("host-address")) and not runtime.reaches_host_loopback():
            port = plan.start_relay(runtime, image_tag, platform, run_dir, port)
            info["relay"] = "a container on the engine's network, port %d" % port
        plan.container_env["EMU_DRIVER_AUDIO_HOST"] = "%s:%d" % (options.get("host-address") or runtime.host_address(),
                                                                 port)
        plan.audio["path"] = "the target's shim device, over TCP"
    if drivers.get("hwrng") == "host":
        bind = options.get("host-bind") or _container_bind_address(runtime)
        info = plan.start_host_process("hwrng", bind, os.path.join(run_dir, "hwrng-host.trace"))
        port = info["port"]
        chosen = options.get("host-bind") or options.get("host-address")
        if not chosen and not runtime.reaches_host_loopback():
            port = plan.start_relay(runtime, image_tag, platform, run_dir, port)
            info["relay"] = "a container on the engine's network, port %d" % port
        address = options.get("host-address") or runtime.host_address()
        plan.container_env["EMU_DRIVER_HWRNG_HOST"] = "%s:%d" % (address, port)
    return plan
