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
import struct
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
# QEMU's displays that open a window, in order of preference. SDL's window
# takes the size of the target's display; GTK's gives the display its own.
WINDOWS = ("sdl", "cocoa", "gtk")
# The ones that can show a display that is rendered on the host GPU.
OPENGL_WINDOWS = ("sdl", "gtk")
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


def window_backend(binary):
    """The QEMU display that shows the emulator's display in a window."""
    displays = _qemu_output(binary, "-display", "help").split()
    for name in WINDOWS:
        if name in displays:
            return name
    raise EmuError("this QEMU build has no display that opens a window (%s)" % ", ".join(WINDOWS))


def probe_vm(binary, window=None):
    """Whether this QEMU can map the guest's graphics to the host's GPU.

    That needs the virtio-gpu device with a host renderer (virglrenderer) and
    a display that gives it a GPU context: the window (`window` names QEMU's
    display for it) when the emulator's display is shown in one, and otherwise
    a display backend that renders without a window.
    """
    key = (binary, window)
    if key in _probes:
        return _probes[key]
    devices = _qemu_output(binary, "-device", "help")
    displays = _qemu_output(binary, "-display", "help")
    # Vulkan is mapped as well where vm_arguments turns that on.
    venus = host.host_os() == "linux" and "venus" in _qemu_output(binary, "-device", "virtio-gpu-gl-pci,help")
    mapped = "QEMU maps the target's OpenGL ES%s to the host GPU (virtio-gpu with virglrenderer)" \
             % (" and Vulkan" if venus else "")
    if "virtio-gpu-gl-pci" not in devices:
        probe = {"available": False,
                 "reason": "this QEMU build has no GPU-accelerated display device (virtio-gpu-gl); "
                           "it was built without virglrenderer"}
    elif window in OPENGL_WINDOWS:
        probe = {"available": True, "venus": venus, "reason": mapped + " and shows it in an OpenGL window"}
    elif window:
        probe = {"available": False,
                 "reason": "QEMU's %s window does not show a display that is rendered on the host GPU" % window}
    elif "egl-headless" not in displays:
        probe = {"available": False,
                 "reason": "this QEMU build has no display backend that renders on the host GPU without a window "
                           "(egl-headless)"}
    elif host.host_os() == "windows":
        # Seen with QEMU 11.1.0: OpenGL ES and Flutter render on the host GPU
        # (virglrenderer on ANGLE), and every frame read from the display is
        # black.
        probe = {"available": False,
                 "reason": "on Windows, QEMU's display that renders on the host GPU without a window "
                           "(egl-headless) stays black: the target renders on the host GPU, but no frame "
                           "reaches the emulator's display. In a window (--window) it does"}
    else:
        probe = {"available": True, "venus": venus, "reason": mapped}
    _probes[key] = probe
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
        where = "; the engine runs in a virtual machine that offers none" if host.host_os() != "linux" else ""
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
    backend, device description). The display is shown in a window when the
    plan names one, and nowhere otherwise."""
    size = "xres=%d,yres=%d" % (width, height)
    window = plan.get("window")
    if plan["provider"] != "host":
        # An emulated display adapter without 3D. Its frame-buffer allowance
        # has to grow with the resolution.
        allowance = max(256, (width * height * 4 * 16) >> 20)
        return (["-device", "virtio-gpu-pci,%s,max_hostmem=%dM" % (size, allowance)], window or "none",
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
    return arguments + ["-device", device], window + ",gl=on" if window else "egl-headless", description


def container_arguments(plan):
    """Container runtime arguments for the chosen provider."""
    return ["--device", "/dev/dri"] if plan["provider"] == "host" else []


# ---------------------------------------------------------- captures ---

def _connect(address):
    """Connect to a socket QEMU listens on (a TCP address or a socket path),
    waiting for QEMU to open it."""
    deadline = time.time() + 30
    while True:
        try:
            if isinstance(address, tuple):
                return socket.create_connection(address, timeout=30)
            found = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            found.settimeout(30)
            found.connect(address)
            return found
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(0.1)


class Qmp:
    """Minimal client for QEMU's machine protocol, used to capture the display."""

    def __init__(self, address):
        self.address = address
        self._socket = None
        self._buffer = b""

    def capture(self, path, image_format):
        self.command("screendump", filename=os.path.abspath(path), format=image_format)

    def _connect(self):
        self._socket = _connect(self.address)
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


class Vnc:
    """Minimal client for QEMU's VNC server, used to capture the display
    where QEMU will not write the image itself."""

    def __init__(self, address):
        self.address = address

    def close(self):
        pass

    def capture(self, path, image_format):
        # A connection per capture: the server states the display's size when
        # one opens, and the target changes that size when it sets a mode.
        connection = _connect(self.address)
        try:
            width, height, pixels = self._frame(connection)
        finally:
            connection.close()
        rgb = bytearray(width * height * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = pixels[2::4], pixels[1::4], pixels[0::4]
        imagefile.save(path, width, height, rgb, image_format)

    @staticmethod
    def _frame(connection):
        def receive(count):
            data = bytearray()
            while len(data) < count:
                chunk = connection.recv(min(count - len(data), 1 << 20))
                if not chunk:
                    raise OSError("QEMU closed the VNC connection")
                data += chunk
            return data

        receive(12)                                         # the server's protocol version
        connection.sendall(b"RFB 003.008\n")
        if 1 not in receive(receive(1)[0]):                 # 1: no authentication
            raise OSError("QEMU's VNC server does not accept a connection without authentication")
        connection.sendall(b"\x01")
        if receive(4) != b"\0\0\0\0":
            raise OSError("QEMU's VNC server refused the connection")
        connection.sendall(b"\x01")                         # share the display with other clients
        width, height = struct.unpack(">HH", receive(20)[:4])
        receive(struct.unpack(">I", receive(4))[0])         # the display's name
        # Pixels as four bytes: blue, green, red, unused. Raw encoding only.
        connection.sendall(struct.pack(">BxxxBBBBHHHBBBxxx", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        connection.sendall(struct.pack(">BxHi", 2, 1, 0))
        connection.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, width, height))
        pixels = bytearray(width * height * 4)
        covered = 0
        while covered < width * height:
            kind = receive(1)[0]
            if kind == 2:                                   # bell
                continue
            if kind == 3:                                   # text from the server's clipboard
                receive(struct.unpack(">xxxI", receive(7))[0])
                continue
            if kind != 0:
                raise OSError("unexpected VNC message %d from QEMU" % kind)
            for _ in range(struct.unpack(">xH", receive(3))[0]):
                x, y, w, h, encoding = struct.unpack(">HHHHi", receive(12))
                if encoding != 0:
                    raise OSError("QEMU's VNC server sent encoding %d, not raw pixels" % encoding)
                data = receive(w * h * 4)
                for row in range(h):
                    start = ((y + row) * width + x) * 4
                    pixels[start:start + w * 4] = data[row * w * 4:(row + 1) * w * 4]
                covered += w * h
        return width, height, pixels


class NoCapture:
    """Stands in where the display cannot be captured, and says why."""

    def __init__(self, reason):
        self.reason = reason

    def capture(self, path, image_format):
        raise EmuError(self.reason)

    def close(self):
        pass


def capture_endpoint(plan):
    """How the display of a VM is captured during one run. Returns (QEMU
    arguments, a client with capture(path, format) and close(), directory to
    remove afterwards).

    QEMU writes the image itself when asked over its machine protocol. It
    refuses while the display is a texture on the host GPU; the image then
    comes from QEMU's VNC server, which the headless display feeds each frame.
    A window that shows such a display feeds nobody, so there is no capture.
    """
    if plan["provider"] == "host" and plan.get("window"):
        return [], NoCapture("QEMU has no way to capture a display that is rendered on the host GPU and shown "
                             "in a window"), None
    kind, client = ("vnc", Vnc) if plan["provider"] == "host" else ("qmp", Qmp)
    if host.host_os() != "windows" and hasattr(socket, "AF_UNIX"):
        # A short private path: socket paths have a tight length limit.
        directory = tempfile.mkdtemp(prefix="emu-", dir="/tmp")
        path = os.path.join(directory, kind + ".sock")
        arguments = ["-vnc", "unix:" + path] if kind == "vnc" else ["-qmp", "unix:%s,server=on,wait=off" % path]
        return arguments, client(path), directory
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    if kind == "vnc":
        # QEMU counts VNC displays from port 5900.
        while port < 5900:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
        return ["-vnc", "127.0.0.1:%d" % (port - 5900)], client(("127.0.0.1", port)), None
    return ["-qmp", "tcp:127.0.0.1:%d,server=on,wait=off" % port], client(("127.0.0.1", port)), None


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
