"""VM mode: the target OS kernel and userland in a QEMU virtual machine."""
import base64
import subprocess

from . import host
from .errors import EmuError

QEMU_BINARY = {"x86_64": "qemu-system-x86_64", "arm64": "qemu-system-aarch64", "arm32": "qemu-system-arm"}
MACHINE = {"x86_64": "q35", "arm64": "virt", "arm32": "virt"}
CONSOLE = {"x86_64": "ttyS0", "arm64": "ttyAMA0", "arm32": "ttyAMA0"}
NATIVE_ACCELERATOR = {"macos": "hvf", "linux": "kvm", "windows": "whpx"}
# Target CPUs simulated when the guest architecture is not run natively.
SIMULATED_CPU = {"arm64": "cortex-a53", "arm32": "cortex-a15", "x86_64": "max"}


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
    return accelerator == "whpx" and system == "windows"


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
            cpu = "host" if accelerator in ("kvm", "hvf") else "max"
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


def kernel_command_line(guest, workload, args, drivers, verbose, terminal=None):
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
    return " ".join(parts)


def run_command(resolved, artifacts, data_disk, cmdline, cpus, memory_mb, console_on_tty, extra_args, options):
    guest = resolved["guest_arch"]
    binary = host.require_tool(QEMU_BINARY[guest], "VM mode with a %s guest" % guest)
    disk_cache = options.get("disk-cache")
    cache = ",cache=%s" % disk_cache if disk_cache else ""
    command = [
        binary, "-name", "emu-target", "-nodefaults", "-display", "none", "-no-reboot",
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
    # Ctrl-C goes to the target. On a terminal, Ctrl-A X quits the emulator.
    mux = ",mux=on" if console_on_tty else ""
    command += ["-chardev", "stdio,id=console,signal=off" + mux, "-serial", "chardev:console", "-monitor", "none"]
    return command + list(extra_args), binary
