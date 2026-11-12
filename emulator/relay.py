"""A path from containers to a host-side process where the engine has none.

Podman's engine on Windows runs in WSL, whose network lets Windows open
connections into the engine but not the engine open one to a process that
listens on Windows' loopback address. The relay is a listener inside the
engine, started as a container on the engine's own network. It carries every
connection it accepts to the host over the container's standard streams, and
the host half hands each one on to the host-side process.

Both halves are in this file: the engine half is this source, run by the
target image's Python, so it uses the standard library only.
"""
import base64
import json
import socket
import struct
import subprocess
import sys
import threading

_HEADER = struct.Struct(">cII")     # kind, connection, length of the data
OPEN, DATA, CLOSE = b"O", b"D", b"C"
_BOOT = "import base64,sys;exec(compile(base64.b64decode(sys.argv[1]),'relay','exec'))"


class _Link:
    """Connections carried side by side over one pair of byte streams."""

    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer
        self._lock = threading.Lock()
        self._sockets = {}

    def send(self, kind, ident, data=b""):
        with self._lock:
            self._writer.write(_HEADER.pack(kind, ident, len(data)) + data)
            self._writer.flush()

    def attach(self, ident, sock):
        """Carry what the socket receives to the other end."""
        self._sockets[ident] = sock
        threading.Thread(target=self._outbound, args=(ident, sock), daemon=True).start()

    def _outbound(self, ident, sock):
        try:
            for data in iter(lambda: sock.recv(65536), b""):
                self.send(DATA, ident, data)
            self.send(CLOSE, ident)
        except (OSError, ValueError):
            pass

    def serve(self, connect=None):
        """Deliver what the other end sends until its stream ends. `connect`
        opens the local socket for a connection the other end accepted."""
        while True:
            header = self._reader.read(_HEADER.size)
            if len(header) < _HEADER.size:
                return
            kind, ident, length = _HEADER.unpack(header)
            data = self._reader.read(length) if length else b""
            try:
                if kind == OPEN and connect:
                    self.attach(ident, connect())
                elif kind == DATA and ident in self._sockets:
                    self._sockets[ident].sendall(data)
                elif kind == CLOSE and ident in self._sockets:
                    sock = self._sockets.pop(ident)
                    try:
                        sock.shutdown(socket.SHUT_RDWR)     # wakes the thread that reads it
                    except OSError:
                        pass
                    sock.close()
            except OSError:
                if kind == OPEN:
                    self.send(CLOSE, ident)


def engine_main():
    """The half inside the engine: accept connections, carry them to the host."""
    link = _Link(sys.stdin.buffer, sys.stdout.buffer)
    listener = socket.create_server(("0.0.0.0", 0))
    sys.stdout.buffer.write((json.dumps({"port": listener.getsockname()[1]}) + "\n").encode())
    sys.stdout.buffer.flush()

    def accept():
        ident = 0
        while True:
            sock, _ = listener.accept()
            ident += 1
            link.send(OPEN, ident)
            link.attach(ident, sock)

    threading.Thread(target=accept, daemon=True).start()
    link.serve()    # returns when the host closes the stream, which ends the container


class Relay:
    """The host half. `target` is the (address, port) of the host-side process;
    `port` is where containers reach it, under the runtime's name for the host."""

    def __init__(self, runtime, image_tag, platform, name, target, env, log_path):
        self._runtime = runtime
        self._name = name
        with open(__file__, "rb") as handle:
            source = base64.b64encode(handle.read()).decode()
        command = [runtime.cli, "run", "--rm", "--interactive", "--network", "host", "--name", name,
                   "--platform", platform, "--entrypoint", "python3", image_tag, "-c", _BOOT, source]
        with open(log_path, "wb") as log:
            self._child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, env=env)
        try:
            self.port = json.loads(self._child.stdout.readline())["port"]
        except (ValueError, KeyError):
            self.stop()
            with open(log_path, errors="replace") as log:
                raise RuntimeError(log.read().strip() or "the relay container gave no startup message")

        def connect():
            sock = socket.create_connection(target, timeout=10)
            sock.settimeout(None)
            return sock

        link = _Link(self._child.stdout, self._child.stdin)
        threading.Thread(target=link.serve, args=(connect,), daemon=True).start()

    def stop(self):
        try:
            self._child.stdin.close()   # the engine half ends when its input does
        except OSError:
            pass
        try:
            self._child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._runtime.run("rm", "--force", self._name)
            self._child.kill()
            self._child.wait()
        self._child.stdout.close()


if __name__ == "__main__":
    engine_main()
