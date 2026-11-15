"""The launcher's side of its windows (emulator/gui): finding the Python that
has Qt, and starting a window as a program of its own.

The windows are built with Qt 6 through PySide6. The setup scripts install it
into a Python environment of the project's own, build/host/gui, so that the
host's Python stays as it is; the launcher itself needs only Python's standard
library.
"""
import json
import os
import socket
import subprocess
import sys
import threading

from . import host
from .errors import EmuError
from .paths import BUILD_DIR, ROOT

GUI_DIR = BUILD_DIR / "host" / "gui"
PACKAGE = "PySide6-Essentials"
# Says which Python runs the windows, in place of the two below.
PYTHON_VARIABLE = "EMU_GUI_PYTHON"


def _has_qt(python):
    try:
        done = subprocess.run([str(python), "-c", "import PySide6.QtWidgets"], capture_output=True, timeout=120)
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def environment_python():
    """The Python of the project's own environment, whether it exists or not."""
    return GUI_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def gui_python():
    """The Python that runs the windows, or None when there is none with Qt."""
    named = os.environ.get(PYTHON_VARIABLE)
    for candidate in ([named] if named else [environment_python(), sys.executable]):
        if os.path.exists(str(candidate)) and _has_qt(candidate):
            return str(candidate)
    return None


def require_python(purpose):
    found = gui_python()
    if not found:
        raise EmuError("%s needs Qt for Python (%s), which is not installed" % (purpose, PACKAGE),
                       hint=host.SETUP_HINT)
    return found


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _environment():
    path = os.environ.get("PYTHONPATH")
    return host.tool_env({"PYTHONPATH": str(ROOT) + (os.pathsep + path if path else ""),
                          "PYTHONDONTWRITEBYTECODE": "1"})


class Viewer:
    """The display window of one run, as a process."""

    def __init__(self, process, control):
        self.process = process
        self.control = control
        self._lock = threading.Lock()

    def ask(self, **command):
        """One command for the window, and its answer (only with control)."""
        with self._lock:
            try:
                self.process.stdin.write(json.dumps(command) + "\n")
                self.process.stdin.flush()
                answer = self.process.stdout.readline()
            except (OSError, ValueError):
                answer = ""
        if not answer:
            raise EmuError("the display window ended: %s" % self.errors())
        return json.loads(answer)

    def errors(self):
        try:
            return (self.process.stderr.read() or "").strip()[-600:] if self.process.stderr else ""
        except (OSError, ValueError):
            return ""

    def running(self):
        return self.process.poll() is None

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


def start_viewer(display, title, fullscreen=False, remote_control=None, keys_exec=None, keys_listen=None,
                 audio_port=None, control=False):
    """Start the display window. `display` is where the target's display is
    served: a socket path or a (host, port) pair."""
    python = require_python("the emulator's display window")
    address = "%s:%d" % display if isinstance(display, tuple) else str(display)
    command = [python, "-m", "emulator.gui.viewer", "--display", address, "--title", title]
    if fullscreen:
        command.append("--fullscreen")
    if remote_control:
        command += ["--remote-control", remote_control]
    if keys_exec:
        command += ["--keys-exec", json.dumps(list(keys_exec))]
    if keys_listen:
        command += ["--keys-listen", str(keys_listen)]
    if audio_port:
        command += ["--audio-control", str(audio_port)]
    if control:
        command.append("--control")
    pipe = subprocess.PIPE if control else subprocess.DEVNULL
    try:
        process = subprocess.Popen(command, stdin=pipe, stdout=pipe, stderr=subprocess.PIPE if control else None,
                                   text=True, env=_environment())
    except OSError as error:
        raise EmuError("the display window could not be started: %s" % error)
    return Viewer(process, control)


def choose_settings(arguments=None, script=None):
    """Show the settings window; returns the launcher arguments the user
    started the emulator with, or None when the window was closed instead.
    `script` is for the checks: what to set and press, in place of a person."""
    python = require_python("the settings window")
    command = [python, "-m", "emulator.gui.settings"]
    if script is not None:
        command += ["--script", json.dumps(script)]
    done = subprocess.run(command + list(arguments or []), stdout=subprocess.PIPE, text=True, env=_environment())
    if done.returncode != 0:
        raise EmuError("the settings window ended with status %d" % done.returncode)
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    chosen = json.loads(lines[-1]) if lines else {}
    return chosen if script is not None else chosen.get("arguments")
