"""The emulator's display, and how its graphics functionality is provided.

The display has one of the supported resolutions. Graphics are provided in
one of two ways:

  emulated  the target's CPU renders (Mesa's software OpenGL ES and Vulkan);
            the emulator only shows the result
  host      graphics are mapped to the host's graphics acceleration

"auto" prefers host acceleration when the host has a compatible one and
falls back to emulation; the reason for the choice is recorded with the run.
What the target actually rendered with is reported by the workload, so a
result never depends on this module's expectation alone.
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time

from . import host, imagefile
from .errors import EmuError

RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}
DEFAULT_RESOLUTION = "1080p"
CHOICES = ("auto", "host", "emulated")
# How long a workload keeps its last frame on the display for a capture.
SCREEN_HOLD_SECONDS = 4
# Marker blocks every graphics workload draws (target/src/emugfx.c): the four
# corners, in the order top left, top right, bottom left, bottom right.
CORNER_COLORS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))
COLOR_TOLERANCE = 12

_probes = {}


def resolution(name):
    try:
        return RESOLUTIONS[(name or DEFAULT_RESOLUTION).lower()]
    except KeyError:
        raise EmuError("unknown resolution %r (supported: %s)" % (name, ", ".join(RESOLUTIONS)))


def _qemu_output(binary, *args):
    try:
        done = subprocess.run([binary] + list(args), env=host.tool_env(), capture_output=True, text=True, timeout=60)
        return done.stdout + done.stderr
    except (OSError, subprocess.SubprocessError):
        return ""


def probe_vm(binary):
    """Whether this QEMU can map the guest's graphics to the host's GPU.

    That needs the virtio-gpu device with a host renderer (virglrenderer) and
    a display backend that gives it a GPU context without opening a window.
    """
    if binary in _probes:
        return _probes[binary]
    devices = _qemu_output(binary, "-device", "help")
    displays = _qemu_output(binary, "-display", "help")
    if "virtio-gpu-gl-pci" not in devices:
        probe = {"available": False,
                 "reason": "this QEMU build has no GPU-accelerated display device (virtio-gpu-gl); "
                           "it was built without virglrenderer"}
    elif "egl-headless" not in displays:
        probe = {"available": False,
                 "reason": "this QEMU build has no display backend that renders on the host GPU without a window "
                           "(egl-headless)"}
    else:
        venus = "venus" in _qemu_output(binary, "-device", "virtio-gpu-gl-pci,help")
        probe = {"available": True, "venus": venus,
                 "reason": "QEMU maps the target's OpenGL ES%s to the host GPU (virtio-gpu with virglrenderer)"
                           % (" and Vulkan" if venus else "")}
    _probes[binary] = probe
    return probe


def probe_container(runtime, tag, platform):
    """Whether the container engine has a GPU render node to give the target."""
    key = (runtime.cli, tag)
    if key in _probes:
        return _probes[key]
    try:
        done = runtime.run("run", "--rm", "--platform", platform, "--device", "/dev/dri", "--entrypoint", "/bin/sh",
                           tag, "-c", "ls /dev/dri/renderD* 2>/dev/null | head -n 1", timeout=120)
        node = done.stdout.strip() if done.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        node = ""
    if node:
        probe = {"available": True, "reason": "the container engine has a GPU render node (%s)" % node}
    else:
        where = "; the engine runs in a virtual machine that has no GPU" if host.host_os() != "linux" else ""
        probe = {"available": False, "reason": "the container engine has no GPU render node (/dev/dri)" + where}
    _probes[key] = probe
    return probe


def choose(requested, probe):
    """Decide the graphics provider. `probe` is a callable so that asking for
    emulation never touches the host's graphics."""
    requested = requested or "auto"
    if requested not in CHOICES:
        raise EmuError("unknown --graphics %r (one of: %s)" % (requested, ", ".join(CHOICES)))
    if requested == "emulated":
        return {"requested": requested, "provider": "emulated", "reason": "emulation was requested"}
    found = probe()
    if found["available"]:
        return {"requested": requested, "provider": "host", "reason": found["reason"],
                "venus": bool(found.get("venus"))}
    if requested == "host":
        raise EmuError("host graphics acceleration is not available: %s" % found["reason"],
                       hint="use --graphics auto to fall back to emulated graphics")
    return {"requested": requested, "provider": "emulated",
            "reason": "no compatible host graphics acceleration: %s" % found["reason"]}


def vm_arguments(plan, width, height, memory_mb, options):
    """QEMU arguments for the display device; returns (arguments, display
    backend, device description)."""
    size = "xres=%d,yres=%d" % (width, height)
    if plan["provider"] != "host":
        # An emulated display adapter without 3D. Its frame-buffer allowance
        # has to grow with the resolution.
        allowance = max(256, (width * height * 4 * 16) >> 20)
        return (["-device", "virtio-gpu-pci,%s,max_hostmem=%dM" % (size, allowance)], "none",
                "virtio-gpu (2D), rendering by the target CPU")
    device = "virtio-gpu-gl-pci," + size
    arguments = []
    description = "virtio-gpu with virglrenderer (OpenGL ES on the host GPU)"
    venus = str(options.get("venus", "auto")).lower()
    if venus in ("yes", "on", "true", "1") or (venus == "auto" and plan.get("venus") and host.host_os() == "linux"):
        # Vulkan pass-through shares guest memory with the host renderer.
        device += ",venus=on,blob=on,hostmem=4G"
        arguments += ["-object", "memory-backend-memfd,id=emu-ram,size=%dM" % memory_mb,
                      "-machine", "memory-backend=emu-ram"]
        description = "virtio-gpu with virglrenderer (OpenGL ES and Vulkan on the host GPU)"
    return arguments + ["-device", device], "egl-headless", description


def container_arguments(plan):
    """Container runtime arguments for the chosen provider."""
    return ["--device", "/dev/dri"] if plan["provider"] == "host" else []


# ---------------------------------------------------------- captures ---

class Qmp:
    """Minimal client for QEMU's machine protocol, used to capture the display."""

    def __init__(self, address):
        self.address = address
        self._socket = None
        self._buffer = b""

    def _connect(self):
        deadline = time.time() + 30
        while True:
            try:
                if isinstance(self.address, tuple):
                    self._socket = socket.create_connection(self.address, timeout=30)
                else:
                    self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self._socket.settimeout(30)
                    self._socket.connect(self.address)
                break
            except OSError:
                self._socket = None
                if time.time() > deadline:
                    raise
                time.sleep(0.1)
        self._read()            # greeting
        self.command("qmp_capabilities")

    def _read(self):
        while b"\n" not in self._buffer:
            chunk = self._socket.recv(65536)
            if not chunk:
                raise OSError("QEMU closed the machine protocol connection")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return json.loads(line)

    def command(self, name, **arguments):
        if self._socket is None:
            self._connect()
        self._socket.sendall(json.dumps({"execute": name, "arguments": arguments}).encode() + b"\n")
        while True:
            reply = self._read()
            if "return" in reply:
                return reply["return"]
            if "error" in reply:
                raise OSError("QEMU refused %s: %s" % (name, reply["error"].get("desc")))

    def close(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None


def qmp_endpoint():
    """Where QEMU listens for the machine protocol during one run. Returns
    (QEMU arguments, address for Qmp, directory to remove afterwards)."""
    if host.host_os() != "windows" and hasattr(socket, "AF_UNIX"):
        # A short private path: socket paths have a tight length limit.
        directory = tempfile.mkdtemp(prefix="emu-", dir="/tmp")
        path = os.path.join(directory, "qmp.sock")
        return ["-qmp", "unix:%s,server=on,wait=off" % path], path, directory
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return ["-qmp", "tcp:127.0.0.1:%d,server=on,wait=off" % port], ("127.0.0.1", port), None


class Screens:
    """Captures the emulator's display each time a workload announces that a
    finished frame is on it (an EMU-SCREEN line)."""

    def __init__(self, directory, run_id, image_format, capture):
        self.directory = directory
        self.run_id = run_id
        self.image_format = image_format
        self._capture = capture        # callable(path) that writes the image
        self.captures = []

    def on_marker(self, marker):
        entry = dict(marker)
        path = os.path.join(str(self.directory), "%s_%s.%s" % (self.run_id, marker.get("test", "screen"),
                                                               self.image_format))
        try:
            os.makedirs(str(self.directory), exist_ok=True)
            self._capture(path)
            entry["file"] = path
            entry["captured_width"], entry["captured_height"] = imagefile.size(path)
        except (OSError, EmuError, ValueError, subprocess.SubprocessError) as error:
            entry["error"] = "%s" % error
        self.captures.append(entry)


def vm_capture(qmp, image_format):
    def capture(path):
        qmp.command("screendump", filename=os.path.abspath(path), format=image_format)
    return capture


def container_capture(runtime, name):
    def capture(path):
        with open(path, "wb") as handle:
            done = subprocess.run([runtime.cli, "exec", name, "/opt/emu/display", "screenshot"], env=host.tool_env(),
                                  stdout=handle, stderr=subprocess.PIPE, timeout=120)
        if done.returncode != 0:
            raise EmuError("the target could not capture its display: %s"
                           % done.stderr.decode(errors="replace").strip()[-300:])
    return capture


def _close(found, expected):
    return all(abs(a - b) <= COLOR_TOLERANCE for a, b in zip(found, expected))


def capture_problems(entry, width, height):
    """Compare a captured display image with what the workload said it drew:
    the display size, the corner blocks and the technology's marker block.
    Returns a list of problems, empty when the capture shows that frame."""
    if entry.get("error"):
        return ["the display could not be captured: %s" % entry["error"]]
    if (entry["captured_width"], entry["captured_height"]) != (width, height):
        return ["the display capture is %dx%d, not %dx%d" % (entry["captured_width"], entry["captured_height"],
                                                             width, height)]
    image = imagefile.load(entry["file"])
    block = height // 12
    half = block // 2
    points = [("top-left corner", half, half, CORNER_COLORS[0]),
              ("top-right corner", width - block + half, half, CORNER_COLORS[1]),
              ("bottom-left corner", half, height - block + half, CORNER_COLORS[2]),
              ("bottom-right corner", width - block + half, height - block + half, CORNER_COLORS[3]),
              ("technology marker", width // 2, half, tuple(entry.get("marker") or ()))]
    problems = []
    for name, x, y, expected in points:
        found = image.pixel(x, y)
        if len(expected) != 3 or not _close(found, expected):
            problems.append("%s is %s, expected %s" % (name, found, expected))
    return problems


def remove_directory(path):
    if path:
        shutil.rmtree(path, ignore_errors=True)
