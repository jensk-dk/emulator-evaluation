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

from . import host
from .errors import EmuError
from .paths import ROOT

STRATEGIES = ("emulated", "mocked", "host")
FEATURES = {
    "hwrng": "hardware random number generator, read by target software from /dev/hwrng",
}
DEFAULT_STRATEGY = "emulated"


def parse(specs):
    """Turn ["hwrng=mocked", ...] into {"hwrng": "mocked"}, applying defaults.
    The strategy "none" leaves a feature out."""
    chosen = {feature: DEFAULT_STRATEGY for feature in FEATURES}
    for spec in specs or []:
        feature, separator, strategy = spec.partition("=")
        if not separator or feature not in FEATURES:
            raise EmuError("bad --driver %r: expected FEATURE=STRATEGY with FEATURE one of: %s"
                           % (spec, ", ".join(sorted(FEATURES))))
        if strategy == "none":
            chosen.pop(feature, None)
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
        self.host_processes = []    # dicts describing running host-side processes
        self._children = []

    def start_host_process(self, feature, bind, trace_path):
        command = [sys.executable, "-m", "emulator.hostd", feature, "--bind", bind]
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

    def stop(self):
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


def plan_vm(drivers, run_dir):
    plan = Plan()
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


def plan_container(drivers, runtime, run_dir, options):
    plan = Plan()
    if drivers.get("hwrng") == "host":
        bind = options.get("host-bind") or _container_bind_address(runtime)
        info = plan.start_host_process("hwrng", bind, os.path.join(run_dir, "hwrng-host.trace"))
        address = options.get("host-address") or runtime.host_address()
        plan.container_env["EMU_DRIVER_HWRNG_HOST"] = "%s:%d" % (address, info["port"])
    return plan
