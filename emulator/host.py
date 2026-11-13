"""Facts about the development host, and where to find its tools."""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys

from .errors import EmuError
from .paths import BUILD_DIR, ROOT

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


def host_tool_dir():
    """Where the launcher keeps the programs it builds for this host."""
    return BUILD_DIR / "host"


def tool_path():
    """PATH extended with the directories package managers install into, and
    with the launcher's own host programs."""
    current = os.environ.get("PATH", "").split(os.pathsep)
    extra = [d for d in _EXTRA_TOOL_DIRS.get(host_os(), []) + [str(host_tool_dir())]
             if os.path.isdir(d) and d not in current]
    return os.pathsep.join(current + extra)


def tool_env(extra=None):
    """Environment for child processes, so tools can find their own helpers."""
    env = dict(os.environ)
    env["PATH"] = tool_path()
    env.update(extra or {})
    return env


def find_tool(name):
    return shutil.which(name, path=tool_path())


MACOS_AUDIO_PLAYER = "emu-coreaudio"


def macos_audio_player():
    """The launcher's audio player for macOS hosts, built from
    emulator/coreaudio_player.c with the system's compiler the first time it
    is needed and again when its source changes. Returns its path."""
    source = ROOT / "emulator" / "coreaudio_player.c"
    program = host_tool_dir() / MACOS_AUDIO_PLAYER
    stamp = program.with_name(program.name + ".sha256")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    try:
        if program.is_file() and stamp.read_text().strip() == digest:
            return str(program)
    except OSError:
        pass
    compiler = find_tool("clang")
    if not compiler:
        raise EmuError("the audio player for macOS cannot be built: no C compiler (clang)",
                       hint="install the Xcode Command Line Tools: xcode-select --install")
    program.parent.mkdir(parents=True, exist_ok=True)
    fresh = program.with_name(program.name + ".new")
    done = subprocess.run([compiler, "-O2", "-o", str(fresh), str(source), "-framework", "AudioToolbox",
                           "-framework", "CoreAudio", "-framework", "CoreFoundation"],
                          capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise EmuError("the audio player for macOS did not build:\n" + done.stderr.strip()[-2000:])
    os.replace(str(fresh), str(program))
    stamp.write_text(digest + "\n")
    return str(program)


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


_gpus = None


def gpus():
    """The host's graphics adapters: [{"model", "driver", "driver_version"}],
    with only the entries the host could tell. Empty when it cannot be found
    out; a result must never fail for it."""
    global _gpus
    if _gpus is None:
        try:
            _gpus = {"linux": _gpus_linux, "macos": _gpus_macos, "windows": _gpus_windows}[host_os()]()
        except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
            _gpus = []
    return _gpus


def _gpu(model, driver=None, driver_version=None):
    found = {"model": " ".join(str(model).split())}
    if driver:
        found["driver"] = driver
    if driver_version:
        found["driver_version"] = str(driver_version).strip()
    return found


def _gpus_linux():
    """PCI display adapters, each with the kernel driver bound to it. Without
    a driver the adapter is there but the host does not render with it."""
    found = []
    lspci = find_tool("lspci")
    listing = _output([lspci, "-D", "-mm"]) if lspci else ""
    for line in listing.splitlines():
        fields = re.findall(r'"([^"]*)"', line)
        if len(fields) < 3 or not re.match(r"(VGA|3D|Display)", fields[0]):
            continue
        slot = line.split()[0]
        # "AD104 [GeForce RTX 4070]": the name in brackets is the product.
        product = re.search(r"\[([^\]]+)\]\s*$", fields[2])
        model = "%s %s" % (fields[1].replace(" Corporation", ""), product.group(1) if product else fields[2])
        driver = version = None
        try:
            driver = os.path.basename(os.readlink("/sys/bus/pci/devices/%s/driver" % slot))
            with open("/sys/module/%s/version" % driver) as handle:      # out-of-tree drivers have one
                version = handle.read().strip()
        except OSError:
            pass
        found.append(_gpu(model, driver, version))
    return found


def _gpus_macos():
    data = json.loads(_output(["system_profiler", "SPDisplaysDataType", "-json"]) or "{}")
    return [_gpu(item.get("sppci_model") or item.get("_name")) for item in data.get("SPDisplaysDataType", [])
            if item.get("sppci_model") or item.get("_name")]


def _gpus_windows():
    text = _output(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion | ConvertTo-Json"])
    data = json.loads(text or "[]")
    return [_gpu(item["Name"], driver_version=item.get("DriverVersion"))
            for item in (data if isinstance(data, list) else [data]) if item.get("Name")]


def gpu_text(found):
    return "%s%s" % (found["model"], " (%s)" % " ".join(
        part for part in (found.get("driver"), found.get("driver_version")) if part)
        if found.get("driver") or found.get("driver_version") else "")


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
        "gpus": gpus(),
        "python": platform.python_version(),
    }


def stdin_is_tty():
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False
