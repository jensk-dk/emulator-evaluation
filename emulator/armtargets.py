"""The simulated ARM64 and ARM32 targets, which a host is set up for only on
request.

They run on a simulated CPU, which is slow, and not every graphics technology
runs in them, so the setup script installs what only they need when it is
asked to (--arm-targets): QEMU's ARM system emulators where they are separate
from the one for the host's own CPU, and the emulation of ARM programs in the
container engine, which building their target images needs. Here the
launcher finds out whether a host has that, so that it can say so instead of
starting a build or a VM that cannot work.
"""
import os
import subprocess

from . import host, image, vm
from .errors import EmuError

ARCHS = ("arm64", "arm32")
NAMES = {"arm64": "ARM64", "arm32": "ARM32"}
# What the kernel of the container engine calls its emulator for each.
EMULATION = {"arm64": "qemu-aarch64", "arm32": "qemu-arm"}
BINFMT = "/proc/sys/fs/binfmt_misc"


def _registered(runtime):
    """The names of the user-mode emulators registered in the kernel that the
    container engine runs on, or None where that is not to be found out."""
    system = host.host_os()
    command = None
    try:
        if system == "linux":
            described = runtime.run("info", "--format", "{{.OperatingSystem}}", timeout=30) \
                if runtime.name == "docker" else None
            if described is not None and "docker desktop" in described.stdout.lower():
                return None             # a virtual machine of its own, which registers every emulator itself
            return os.listdir(BINFMT)
        if runtime.name == "podman":
            command = [runtime.cli, "machine", "ssh", "ls", BINFMT]
        elif system == "macos" and host.find_tool("colima"):
            command = [host.find_tool("colima"), "ssh", "--", "ls", BINFMT]
        if not command:
            return None                 # Docker Desktop
        listed = subprocess.run(command, env=host.tool_env(), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return listed.stdout.split() if listed.returncode == 0 else None


def build_gap(runtime, arch):
    """Why the container engine cannot build the target image of the
    simulated ARM target `arch`, or None: when it can, when that is not to be
    found out, or when the image is one of the host's own architecture."""
    if arch not in ARCHS or arch == host.host_arch():
        return None
    registered = _registered(runtime)
    if registered is None:
        return None
    wanted = EMULATION[arch]
    # The ARM64 emulator is registered under more than one name by some.
    found = any(name == wanted or (arch == "arm64" and name.startswith(wanted)) for name in registered)
    return None if found else ("the container engine has no emulation of %s programs (binfmt), which building "
                               "the target image needs" % NAMES[arch])


def gap(arch, runtime_factory):
    """Why the simulated ARM target `arch` cannot be used on this host as it
    is set up, or None when it can. `runtime_factory` gives the container
    runtime; it is called only when the target's image has yet to be built."""
    if arch not in ARCHS:
        return None
    binary = vm.QEMU_BINARY[arch]
    if not host.find_tool(binary):
        return "QEMU's system emulator for %s guests (%s) is not installed" % (NAMES[arch], binary)
    if arch == host.host_arch() or image.vm_built(arch):
        return None
    try:
        runtime = runtime_factory()
    except EmuError:
        return None                     # no container engine: that is said as what it is
    return build_gap(runtime, arch)


def require(arch, runtime_factory):
    """Stop, with the way to set them up, where the simulated ARM target
    cannot be used on this host."""
    reason = gap(arch, runtime_factory)
    if reason:
        raise EmuError(not_set_up(arch, reason), hint=host.ARM_SETUP_HINT)


def not_set_up(arch, reason):
    return "the simulated %s target is not set up on this host: %s" % (NAMES[arch], reason)
