"""VM mode: the target OS kernel and userland in a QEMU virtual machine."""
import base64
import socket
import subprocess
import time

from . import host
from .errors import EmuError

QEMU_BINARY = {"x86_64": "qemu-system-x86_64", "arm64": "qemu-system-aarch64", "arm32": "qemu-system-arm"}
MACHINE = {"x86_64": "q35", "arm64": "virt", "arm32": "virt"}
CONSOLE = {"x86_64": "ttyS0", "arm64": "ttyAMA0", "arm32": "ttyAMA0"}
NATIVE_ACCELERATOR = {"macos": "hvf", "linux": "kvm", "windows": "whpx"}
# Target CPUs simulated when the guest architecture is not run natively.
SIMULATED_CPU = {"arm64": "cortex-a53", "arm32": "cortex-a15", "x86_64": "max"}
# The host's own CPU under each hypervisor. QEMU has no "host" model for WHPX,
# and its "max" model announces nested virtualization, which WHPX does not
# provide: a guest that is told it has it fails in its first second.
ACCELERATED_CPU = {"kvm": "host", "hvf": "host", "whpx": "max,-vmx,-svm"}
# What QEMU prints when a hypervisor stops running the guest for good. QEMU
# itself keeps running after that, so the launcher has to end it.
GAVE_UP = ("WHPX: Unexpected VP exit code",)


def qemu_version(binary):
    try:
        done = subprocess.run([binary, "--version"], env=host.tool_env(), capture_output=True, text=True, timeout=30)
        return done.stdout.splitlines()[0].strip()
    except (OSError, IndexError, subprocess.SubprocessError):
        return "QEMU (unknown version)"


def _accelerator_available(accelerator):
    system = host.host_os()
    if accelerator == "kvm":
        try:
            open("/dev/kvm", "r+b").close()
            return True
        except OSError:
            return False
    if accelerator == "hvf":
        try:
            done = subprocess.run(["sysctl", "-n", "kern.hv_support"], capture_output=True, text=True, timeout=10)
            return done.stdout.strip() == "1"
        except (OSError, subprocess.SubprocessError):
            return False
    return accelerator == "whpx" and system == "windows" and _whpx_available()


def _whpx_available():
    """Whether the Windows Hypervisor Platform can run a VM right now.

    Asks the platform's own API, as QEMU does. The state of the optional
    Windows feature does not say: the API also works when another feature
    (the one WSL 2 uses) keeps the hypervisor running, and does not work yet
    while a newly enabled feature waits for a restart."""
    try:
        import ctypes
        api = ctypes.WinDLL("WinHvPlatform.dll")
        buffer = (ctypes.c_ubyte * 256)()       # larger than any capability
        written = ctypes.c_uint32(0)
        api.WHvGetCapability.restype = ctypes.c_long
        hypervisor_present = 0                  # WHvCapabilityCodeHypervisorPresent
        result = api.WHvGetCapability(hypervisor_present, ctypes.byref(buffer), ctypes.sizeof(buffer),
                                      ctypes.byref(written))
        return result == 0 and any(buffer[:4])
    except (OSError, AttributeError):
        return False


def resolve(arch_choice, accelerator=None, cpu=None):
    """Decide the guest architecture, accelerator and CPU model.

    "native" runs the host's own architecture on the host's hypervisor. The
    named architectures simulate a target CPU with QEMU's emulator unless an
    accelerator is asked for explicitly.
    """
    native = arch_choice == "native"
    guest = host.host_arch() if native else arch_choice
    notes = []
    if native and not accelerator:
        accelerator = NATIVE_ACCELERATOR[host.host_os()]
        if not _accelerator_available(accelerator):
            notes.append("hardware virtualization (%s) is unavailable; falling back to emulation" % accelerator)
            accelerator = "tcg"
    accelerator = accelerator or "tcg"
    if not cpu:
        if accelerator == "tcg":
            cpu = "max" if native else SIMULATED_CPU[guest]
        else:
            cpu = ACCELERATED_CPU.get(accelerator, "max")
    return {
        "variant": "vm-native" if native else "vm-%s" % guest,
        "guest_arch": guest,
        "accelerator": accelerator,
        "cpu_model": cpu,
        "machine": MACHINE[guest],
        "notes": notes,
    }


def _escape(path):
    """QEMU option values use the comma as a separator."""
    return str(path).replace(",", ",,")


def kernel_command_line(guest, workload, args, drivers, verbose, terminal=None, display=None, settings=None):
    parts = ["console=" + CONSOLE[guest], "root=/dev/vda", "rootfstype=ext4", "rw", "init=/opt/emu/init",
             "net.ifnames=0", "panic=-1"]
    if terminal:
        # A serial console cannot tell the target what terminal is attached.
        parts.append("emu.term=%s:%dx%d" % terminal)
    if not verbose:
        parts += ["quiet", "loglevel=3"]
    parts.append("emu.workload=" + workload)
    if args:
        for arg in args:
            if "\n" in arg:
                raise EmuError("workload arguments cannot contain a newline")
        parts.append("emu.args=" + base64.b64encode("\n".join(args).encode()).decode())
    if drivers:
        parts.append("emu.drivers=" + ",".join("%s=%s" % item for item in sorted(drivers.items())))
    if display:
        # The display the emulator gives the target (emulator/graphics.py).
        parts += ["emu.display=%dx%d" % (display["width"], display["height"]), "emu.graphics=" + display["provider"]]
        if display.get("screen_hold"):
            parts.append("emu.screenhold=%d" % display["screen_hold"])
    # What driver features tell the target (emulator/drivers.py).
    parts += ["emu.%s=%s" % item for item in sorted((settings or {}).items())]
    return " ".join(parts)


class Console:
    """The target's console on a connection that QEMU opens to the launcher,
    in place of QEMU's standard streams.

    QEMU's console on standard input drops, on Windows, every character that
    arrives before the target has taken the previous one. A person does not
    type that fast; a script does."""

    def __init__(self):
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port = self._listener.getsockname()[1]
        self._connection = None

    def accept(self, process, seconds=60):
        """The connection from the emulator `process`, or None if it ended
        (or the time passed) without opening one."""
        self._listener.settimeout(0.5)
        deadline = time.time() + seconds
        while self._connection is None and process.poll() is None and time.time() < deadline:
            try:
                self._connection = self._listener.accept()[0]
            except socket.timeout:
                pass
        return self._connection

    def close(self):
        for item in (self._connection, self._listener):
            if item:
                item.close()


def run_command(resolved, artifacts, data_disk, cmdline, cpus, memory_mb, console_on_tty, extra_args, options,
                display_backend="none", console=None):
    guest = resolved["guest_arch"]
    binary = host.require_tool(QEMU_BINARY[guest], "VM mode with a %s guest" % guest)
    disk_cache = options.get("disk-cache")
    cache = ",cache=%s" % disk_cache if disk_cache else ""
    command = [
        binary, "-name", "emu-target", "-nodefaults", "-display", display_backend, "-no-reboot",
        "-machine", resolved["machine"], "-accel", resolved["accelerator"], "-cpu", resolved["cpu_model"],
        "-smp", str(cpus), "-m", str(memory_mb),
        "-kernel", str(artifacts / "vmlinuz"), "-initrd", str(artifacts / "initrd.img"), "-append", cmdline,
        # The root filesystem is never modified: writes go to a discarded overlay.
        "-drive", "if=none,id=root,format=raw,snapshot=on,file=%s" % _escape(artifacts / "rootfs.img"),
        "-device", "virtio-blk-pci,drive=root",
        "-drive", "if=none,id=data,format=raw,file=%s%s" % (_escape(data_disk), cache),
        "-device", "virtio-blk-pci,drive=data",
        "-netdev", "user,id=net0", "-device", "virtio-net-pci,netdev=net0",
    ]
    if console:
        backend = "socket,id=console,host=127.0.0.1,port=%d" % console.port
    else:
        # Ctrl-C goes to the target. On a terminal, Ctrl-A X quits the emulator.
        backend = "stdio,id=console,signal=off" + (",mux=on" if console_on_tty else "")
    command += ["-chardev", backend, "-serial", "chardev:console", "-monitor", "none"]
    return command + list(extra_args), binary
