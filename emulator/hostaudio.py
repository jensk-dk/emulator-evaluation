"""Host-side process of the "audio" driver feature (see emulator/hostd.py).

The target's sound device sends what target software plays: 16-bit stereo at
48 kHz. This process plays it through the host OS audio path and is where the
emulator's audio is muted and unmuted while it runs.

  target software -> target sound device -> this process -> host OS audio

The samples arrive in one of two ways. In container mode, and wherever the
target has no sound hardware, the target's device opens a TCP connection. In
VM mode the emulated sound card's backend writes them, as a WAV stream, into
a named pipe this process reads (--pipe).

It plays through the host's own player program, so the sound goes wherever
the host's sound server sends an application's sound. A control connection
(one JSON object per line, answered the same way) mutes and unmutes:

    {"command": "mute"}   {"command": "unmute"}   {"command": "toggle"}
    {"command": "status"}

A muted emulator keeps playing: silence goes out in place of the sound, so
the target and the host's sound server see an uninterrupted stream.

With --trace, every tenth of a second of sound is logged as one JSON line:
its level as it arrived and as it was sent on, its pitch, and whether the
emulator was muted. Tests read that to see what the target played.
"""
import array
import json
import math
import os
import shutil
import socketserver
import subprocess
import sys
import threading
import time

RATE = 48000
CHANNELS = 2
FRAME_BYTES = 4
HELLO = b"EMU-PCM s16le 48000 2\n"
WINDOW_BYTES = RATE // 10 * FRAME_BYTES       # the trace's time step
SILENT_RMS = 20.0                           # below this a window counts as silence

# Player programs by host, in order of preference. Each plays raw samples
# from its standard input; "sink" names the host's output device.
PLAYERS = {
    "linux": (
        ("pacat", lambda sink: ["--playback", "--raw", "--format=s16le", "--rate=%d" % RATE,
                                "--channels=%d" % CHANNELS, "--latency-msec=60", "--client-name=emu",
                                "--stream-name=Emulator target audio"] + (["--device=" + sink] if sink else [])),
        ("pw-cat", lambda sink: ["--playback", "--format=s16", "--rate=%d" % RATE, "--channels=%d" % CHANNELS,
                                 "--latency=60ms"] + (["--target=" + sink] if sink else []) + ["-"]),
        ("aplay", lambda sink: ["-q", "-t", "raw", "-f", "S16_LE", "-r", str(RATE), "-c", str(CHANNELS)]
         + (["-D", sink] if sink else [])),
    ),
    # macOS ships no such program. The launcher builds one from
    # emulator/coreaudio_player.c; it plays through an audio queue.
    "macos": (
        ("emu-coreaudio", lambda sink: ["play"] + (["--device", sink] if sink else [])),
    ),
}
# What only the launcher's own player (macOS) can be told: the volume, and a
# file to write everything the host's audio output takes.
PLAYER_SETTINGS = {"volume": "--volume", "monitor": "--monitor"}


def find_player(system, sink, search_path=None, settings=None):
    """The command of the first player program this host has, or (None, why)."""
    names = [name for name, _ in PLAYERS.get(system, ())]
    for name, arguments in PLAYERS.get(system, ()):
        path = shutil.which(name, path=search_path)
        if path:
            command = [path] + arguments(sink)
            if system == "macos":
                for key, option in PLAYER_SETTINGS.items():
                    if (settings or {}).get(key) not in (None, ""):
                        command += [option, str(settings[key])]
            return command, name
    if not names:
        return None, "playing through the host OS is not implemented for %s hosts yet" % system
    if system == "macos":
        return None, "the launcher's audio player (%s) is not built; building it needs the Xcode Command Line " \
                     "Tools" % names[0]
    return None, "none of the player programs is installed (%s)" % ", ".join(names)


def measure(data):
    """(level, pitch) of a block of samples: the root mean square of the left
    channel, and its frequency from the zero crossings."""
    samples = array.array("h")
    samples.frombytes(data[:len(data) - len(data) % FRAME_BYTES])
    if sys.byteorder != "little":
        samples.byteswap()
    left = samples[0::CHANNELS]
    if not left:
        return 0.0, 0.0
    level = math.sqrt(sum(value * value for value in left) / len(left))
    crossings = sum(1 for index in range(1, len(left)) if left[index - 1] < 0 <= left[index])
    return level, crossings * RATE / len(left)


class Output:
    """Where the sound goes: the host's player program, with the mute switch
    and the trace in front of it."""

    def __init__(self, command, player, trace_path, muted):
        self.player = player
        self.muted = muted
        self.received_bytes = 0
        self.played_bytes = 0       # sent to the host with sound in it
        self.muted_bytes = 0        # replaced by silence
        self.streams = 0
        self.player_error = None
        self._command = command
        self._process = None
        self._lock = threading.Lock()
        self._trace = open(trace_path, "w") if trace_path else None
        self._window = b""
        self._window_out = b""
        self._started = time.monotonic()

    def _player(self):
        if self._command and (self._process is None or self._process.poll() is not None):
            if self._process is not None:
                self.player_error = "the player program ended with status %s" % self._process.returncode
            try:
                self._process = subprocess.Popen(self._command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                                 stderr=subprocess.DEVNULL)
            except OSError as error:
                self.player_error = str(error)
                self._command = None
        return self._process

    def write(self, data):
        with self._lock:
            out = bytes(len(data)) if self.muted else data
            self.received_bytes += len(data)
            if self.muted:
                self.muted_bytes += len(data)
            else:
                self.played_bytes += len(data)
            player = self._player()
            if player:
                try:
                    player.stdin.write(out)
                    player.stdin.flush()
                except (OSError, ValueError):
                    pass        # the player ended; the next block restarts it
            if self._trace:
                self._window += data
                self._window_out += out
                while len(self._window) >= WINDOW_BYTES:
                    self._log(self._window[:WINDOW_BYTES], self._window_out[:WINDOW_BYTES])
                    self._window = self._window[WINDOW_BYTES:]
                    self._window_out = self._window_out[WINDOW_BYTES:]

    def _log(self, block, block_out):
        level, pitch = measure(block)
        level_out, _ = measure(block_out)
        self._trace.write(json.dumps({
            "seconds": round(time.monotonic() - self._started, 3), "level": round(level, 1),
            "hz": round(pitch), "sent_level": round(level_out, 1), "muted": self.muted}) + "\n")
        self._trace.flush()

    def set_muted(self, muted):
        with self._lock:
            self.muted = muted

    def status(self):
        with self._lock:
            seconds = lambda count: round(count / (RATE * FRAME_BYTES), 3)
            running = self._process is not None and self._process.poll() is None
            return {"muted": self.muted, "streams": self.streams, "player": self.player,
                    "player_pid": self._process.pid if running else None,
                    "player_error": self.player_error, "received_seconds": seconds(self.received_bytes),
                    "played_seconds": seconds(self.played_bytes), "muted_seconds": seconds(self.muted_bytes)}

    def close(self):
        with self._lock:
            if self._process and self._process.poll() is None:
                try:
                    self._process.stdin.close()
                    self._process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    self._process.kill()
            if self._trace:
                self._trace.close()


class _PcmHandler(socketserver.BaseRequestHandler):
    def handle(self):
        output = self.server.output
        header = b""
        while len(header) < len(HELLO):
            chunk = self.request.recv(len(HELLO) - len(header))
            if not chunk:
                return
            header += chunk
        if header != HELLO:
            return
        with output._lock:
            output.streams += 1
        pending = b""
        while True:
            try:
                chunk = self.request.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            pending += chunk
            whole = len(pending) - len(pending) % FRAME_BYTES
            if whole:
                output.write(pending[:whole])
                pending = pending[whole:]


class _ControlHandler(socketserver.StreamRequestHandler):
    def handle(self):
        output = self.server.output
        for line in self.rfile:
            try:
                command = json.loads(line).get("command")
            except (ValueError, AttributeError):
                command = None
            if command == "mute":
                output.set_muted(True)
            elif command == "unmute":
                output.set_muted(False)
            elif command == "toggle":
                output.set_muted(not output.muted)
            elif command != "status":
                self.wfile.write(json.dumps({"error": "unknown command"}).encode() + b"\n")
                continue
            self.wfile.write(json.dumps(output.status()).encode() + b"\n")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, output):
        super().__init__(address, handler)
        self.output = output


WAV_HEADER_BYTES = 44


def read_pipe(path, output):
    """Take in what the emulator writes into the named pipe: a WAV header,
    then samples, each time it opens the pipe."""
    while True:
        try:
            with open(path, "rb", buffering=0) as pipe:     # waits for the emulator to open it
                header = b""
                while len(header) < WAV_HEADER_BYTES:
                    chunk = pipe.read(WAV_HEADER_BYTES - len(header))
                    if not chunk:
                        break
                    header += chunk
                if len(header) < WAV_HEADER_BYTES:
                    continue
                with output._lock:
                    output.streams += 1
                pending = b""
                while True:
                    chunk = pipe.read(65536)
                    if not chunk:
                        break
                    pending += chunk
                    whole = len(pending) - len(pending) % FRAME_BYTES
                    if whole:
                        output.write(pending[:whole])
                        pending = pending[whole:]
        except OSError:
            return


def control(port, command, timeout=5):
    """Send one command to a running process's control port; returns its answer."""
    import socket
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as connection:
        connection.sendall(json.dumps({"command": command}).encode() + b"\n")
        answer = connection.makefile("rb").readline()
    return json.loads(answer)


def serve(args, system):
    """Run the process; prints its startup line and serves until interrupted."""
    command, player = (None, "none: playing was turned off") if args.player == "none" \
        else find_player(system, args.sink, os.environ.get("PATH"), {"volume": args.volume, "monitor": args.monitor})
    output = Output(command, player, args.trace, args.muted)
    try:
        pcm = _Server((args.bind, args.port), _PcmHandler, output)
        commands = _Server(("127.0.0.1", 0), _ControlHandler, output)
    except OSError as error:
        print(json.dumps({"error": "cannot listen on %s:%d: %s" % (args.bind, args.port, error)}), flush=True)
        return 1
    threading.Thread(target=commands.serve_forever, daemon=True).start()
    if args.pipe:
        try:
            os.mkfifo(args.pipe, 0o600)
        except (OSError, AttributeError) as error:
            print(json.dumps({"error": "cannot make the named pipe %s: %s" % (args.pipe, error)}), flush=True)
            return 1
        threading.Thread(target=read_pipe, args=(args.pipe, output), daemon=True).start()
    print(json.dumps({
        "feature": "audio", "bind": args.bind, "port": pcm.server_address[1],
        "control_port": commands.server_address[1], "pid": os.getpid(), "pipe": args.pipe,
        "source": "the host's player program (%s)" % player if command else "no host output: %s" % player,
        "plays": bool(command), "player": player if command else None, "sink": args.sink,
        "protocol": "pcm s16le %d Hz %d channels" % (RATE, CHANNELS), "muted": args.muted}), flush=True)
    try:
        pcm.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        output.close()
    return 0
