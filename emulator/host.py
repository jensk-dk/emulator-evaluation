"""Facts about the development host, and where to find its tools."""
import os
import platform
import shutil
import subprocess
import sys

from .errors import EmuError

# Package managers install tools in places a minimal PATH does not include.
_EXTRA_TOOL_DIRS = {
    "macos": ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin"],
    "linux": ["/usr/local/bin", "/home/linuxbrew/.linuxbrew/bin"],
    "windows": [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "qemu"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "RedHat", "Podman"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Docker", "Docker", "resources", "bin"),
    ],
}

SETUP_HINT = "run setup.ps1 to install host dependencies" if os.name == "nt" else "run ./setup.sh to install host dependencies"


def host_os():
    system = platform.system()
    try:
        return {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}[system]
    except KeyError:
        raise EmuError("unsupported host operating system: %s" % system)


def _output(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def host_arch():
    machine = platform.machine().lower()
    if host_os() == "macos" and _output(["sysctl", "-n", "hw.optional.arm64"]) == "1":
        return "arm64"      # also when this Python runs translated under Rosetta
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    raise EmuError("unsupported host CPU architecture: %s" % machine)


def host_id():
    return "%s-%s" % (host_os(), host_arch())


def tool_path():
    """PATH extended with the directories package managers install into."""
    current = os.environ.get("PATH", "").split(os.pathsep)
    extra = [d for d in _EXTRA_TOOL_DIRS.get(host_os(), []) if os.path.isdir(d) and d not in current]
    return os.pathsep.join(current + extra)


def tool_env(extra=None):
    """Environment for child processes, so tools can find their own helpers."""
    env = dict(os.environ)
    env["PATH"] = tool_path()
    env.update(extra or {})
    return env


def find_tool(name):
    return shutil.which(name, path=tool_path())


def require_tool(name, purpose):
    path = find_tool(name)
    if not path:
        raise EmuError("%s not found (needed for %s)" % (name, purpose), hint=SETUP_HINT)
    return path


def _cpu_model():
    system = host_os()
    if system == "macos":
        return _output(["sysctl", "-n", "machdep.cpu.brand_string"])
    if system == "linux":
        try:
            with open("/proc/cpuinfo") as handle:
                for line in handle:
                    if line.lower().startswith(("model name", "hardware", "cpu model")):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
        return platform.processor()
    name = _output(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
    return name or platform.processor()


def _memory_bytes():
    system = host_os()
    try:
        if system == "macos":
            return int(_output(["sysctl", "-n", "hw.memsize"]))
        if system == "linux":
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return int(_output(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"]))
    except (ValueError, OSError):
        return None


def _os_version():
    system = host_os()
    if system == "macos":
        return platform.mac_ver()[0]
    if system == "linux":
        try:
            info = platform.freedesktop_os_release()      # Python 3.10+
            return "%s (kernel %s)" % (info.get("PRETTY_NAME", "Linux"), platform.release())
        except (AttributeError, OSError):
            return "kernel %s" % platform.release()
    return platform.version()


def describe():
    """Host identity recorded with every result."""
    return {
        "id": host_id(),
        "os": host_os(),
        "os_version": _os_version(),
        "arch": host_arch(),
        "cpu_model": _cpu_model(),
        "cpus": os.cpu_count(),
        "memory_bytes": _memory_bytes(),
        "python": platform.python_version(),
    }


def stdin_is_tty():
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False
