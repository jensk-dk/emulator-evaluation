"""Remote control input: the keys, the host keys that stand for them, and how
a key press travels to the target.

The key set is HbbTV's list of buttons (ETSI TS 102 796 V1.7.1, Table 12):
what a terminal passes to applications, and the four buttons it handles
itself. Each key is given to the target as a key of a keyboard, with the
Linux key code that names it; the target's compositor has a keyboard for
that, the "remote control" (target/src/emu_remote.c), and a program on the
target's display gets the key like any other.

Three input modes (openspec/specs/remote-control-input):

  keys      host keyboard keys, while the emulator's window has the focus
  window    an on-screen remote control, and the host keys as well
  redrat    infrared signals from a RedRat device: not implemented
"""
import socket
import subprocess
import threading

from . import host

MODES = ("keys", "window", "redrat")
# Ends the remote-keys workload; no remote control key and no host key.
END_KEY = 116

# (id, what the button says, Linux key code, HbbTV's key event or None for a
# button the terminal handles itself)
KEYS = (
    ("up", "Up", 103, "VK_UP"),
    ("down", "Down", 108, "VK_DOWN"),
    ("left", "Left", 105, "VK_LEFT"),
    ("right", "Right", 106, "VK_RIGHT"),
    ("ok", "OK", 28, "VK_ENTER"),
    ("back", "BACK", 158, "VK_BACK"),
    ("0", "0", 11, "VK_0"),
    ("1", "1", 2, "VK_1"),
    ("2", "2", 3, "VK_2"),
    ("3", "3", 4, "VK_3"),
    ("4", "4", 5, "VK_4"),
    ("5", "5", 6, "VK_5"),
    ("6", "6", 7, "VK_6"),
    ("7", "7", 8, "VK_7"),
    ("8", "8", 9, "VK_8"),
    ("9", "9", 10, "VK_9"),
    ("red", "Red", 398, "VK_RED"),
    ("green", "Green", 399, "VK_GREEN"),
    ("yellow", "Yellow", 400, "VK_YELLOW"),
    ("blue", "Blue", 401, "VK_BLUE"),
    ("play", "Play", 207, "VK_PLAY"),
    ("pause", "Pause", 201, "VK_PAUSE"),
    ("play_pause", "Play/pause", 164, "VK_PLAY_PAUSE"),
    ("stop", "Stop", 166, "VK_STOP"),
    ("fast_forward", "Fast forward", 208, "VK_FAST_FWD"),
    ("rewind", "Rewind", 168, "VK_REWIND"),
    ("record", "Record", 167, "VK_RECORD"),
    ("text", "TEXT", 388, None),
    ("channel_up", "P+", 402, None),
    ("channel_down", "P-", 403, None),
    ("webtv", "WEBTV", 150, None),
    ("exit", "EXIT", 174, None),
)
CODES = {key: code for key, _, code, _ in KEYS}
LABELS = {key: label for key, label, _, _ in KEYS}

# Host keyboard key -> remote control key. Host keys are named as the key
# says: a letter or digit, or the key's name. Letters and named keys only, so
# that the keys are where they say on every keyboard layout.
HOST_KEYS = {
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
    "Return": "ok", "Enter": "ok",
    "Backspace": "back",
    "Escape": "exit",
    "0": "0", "1": "1", "2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
    "R": "red", "G": "green", "Y": "yellow", "B": "blue",
    "P": "play", "U": "pause", "Space": "play_pause", "S": "stop",
    "F": "fast_forward", "W": "rewind", "C": "record",
    "T": "text", "PageUp": "channel_up", "PageDown": "channel_down", "H": "webtv",
}


def host_keys_of(key):
    """The host keys that stand for a remote control key."""
    return [name for name, target in HOST_KEYS.items() if target == key]


def problems():
    """What is wrong with the tables above; empty when every remote control
    key has a code of its own and a host key."""
    found = []
    codes = [code for _, _, code, _ in KEYS]
    if len(set(codes)) != len(codes):
        found.append("two remote control keys share a key code")
    if END_KEY in codes:
        found.append("a remote control key has the code that ends the remote-keys workload")
    for key, _, _, _ in KEYS:
        if not host_keys_of(key):
            found.append("no host key stands for the remote control key %r" % key)
    for name, key in HOST_KEYS.items():
        if key not in CODES:
            found.append("host key %r stands for %r, which is no remote control key" % (name, key))
    return found


# ------------------------------------------------------------- senders ---

class Sender:
    """Gives key presses to the target. A press that cannot be delivered is
    dropped, not kept for later."""

    def press(self, code):
        self._send("press %d\n" % code)

    def release(self, code):
        self._send("release %d\n" % code)

    def tap(self, code):
        self.press(code)
        self.release(code)

    def _send(self, line):
        raise NotImplementedError

    def close(self):
        pass


class ExecSender(Sender):
    """Container mode: a program in the container that passes its standard
    input on to the compositor (/opt/emu/remote stdin)."""

    def __init__(self, command):
        self.command = list(command)
        self._process = None
        self._lock = threading.Lock()

    def _send(self, line):
        with self._lock:
            for _ in range(2):
                if self._process is None or self._process.poll() is not None:
                    try:
                        self._process = subprocess.Popen(self.command, stdin=subprocess.PIPE,
                                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                         env=host.tool_env())
                    except OSError:
                        self._process = None
                        return
                try:
                    self._process.stdin.write(line.encode())
                    self._process.stdin.flush()
                    return
                except (OSError, ValueError):
                    self._process = None        # it ended: once more, with a new one

    def close(self):
        with self._lock:
            if self._process is not None:
                try:
                    self._process.stdin.close()
                    self._process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    self._process.kill()
                self._process = None


class ListenSender(Sender):
    """VM mode: the target connects to this port of the host (/opt/emu/remote
    connect), and the lines go down that connection."""

    def __init__(self, port):
        self._listener = socket.create_server(("127.0.0.1", port))
        self._connection = None
        self._lock = threading.Lock()
        self._closing = False
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def connected(self):
        return self._connection is not None

    def _accept(self):
        while not self._closing:
            try:
                connection = self._listener.accept()[0]
            except OSError:
                return
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._lock:
                if self._connection is not None:
                    self._connection.close()
                self._connection = connection       # the newest one: the target connects again after a restart

    def _send(self, line):
        with self._lock:
            if self._connection is None:
                return
            try:
                self._connection.sendall(line.encode())
            except OSError:
                self._connection.close()
                self._connection = None

    def close(self):
        self._closing = True
        self._listener.close()
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
