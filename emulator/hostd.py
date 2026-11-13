"""Host-side processes that serve target driver features from the host OS.

Each feature that uses the "host" strategy gets one of these processes. The
target reaches it through the emulator (a QEMU device backend in VM mode, a
TCP connection in container mode) and the process answers using a host OS
facility.

    python -m emulator.hostd hwrng [--bind ADDRESS] [--port PORT] [--trace FILE]
    python -m emulator.hostd audio [--bind ADDRESS] [--port PORT] [--trace FILE]
                                   [--sink DEVICE] [--player none] [--muted] [--pipe PATH]

On startup it prints one JSON line with the address it listens on.
"""
import argparse
import json
import os
import platform
import socketserver
import sys
import threading


class _EgdHandler(socketserver.BaseRequestHandler):
    """Entropy Gathering Daemon protocol, which QEMU's rng-egd backend and the
    container-side shim both speak. Entropy comes from the host OS generator
    (getentropy, getrandom or BCryptGenRandom, through os.urandom)."""

    def handle(self):
        server = self.server
        while True:
            header = self._receive(2)
            if header is None:
                return
            command, count = header[0], header[1]
            if command == 0x00:                 # entropy available, in bits
                self.request.sendall((4096 * 8).to_bytes(4, "big"))
                continue
            if command not in (0x01, 0x02):     # non-blocking and blocking read
                return
            data = os.urandom(count)
            server.record(data)
            self.request.sendall((bytes([count]) if command == 0x01 else b"") + data)

    def _receive(self, count):
        data = b""
        while len(data) < count:
            try:
                chunk = self.request.recv(count - len(data))
            except OSError:
                return None
            if not chunk:
                return None
            data += chunk
        return data


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, trace_path):
        super().__init__(address, _EgdHandler)
        self._lock = threading.Lock()
        self._trace = open(trace_path, "w") if trace_path else None

    def record(self, data):
        """Append served bytes to the trace, so a test can prove which bytes
        the target received came from this process."""
        if self._trace:
            with self._lock:
                self._trace.write(data.hex())
                self._trace.flush()


FEATURES = {"hwrng": {"source": "host OS entropy (os.urandom)", "protocol": "egd"},
            "audio": {"source": "the host OS audio path", "protocol": "pcm"}}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="emulator.hostd", description=__doc__.splitlines()[0])
    parser.add_argument("feature", choices=sorted(FEATURES))
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--trace", help="hwrng: append every byte served, as hex, to this file; "
                                        "audio: log the sound's level and pitch here")
    parser.add_argument("--sink", help="audio: the host output device to play on (default: the host's default)")
    parser.add_argument("--player", choices=("auto", "none"), default="auto",
                        help="audio: none takes the sound in without playing it")
    parser.add_argument("--muted", action="store_true", help="audio: start muted")
    parser.add_argument("--pipe", help="audio: also take samples from this named pipe, which is created")
    args = parser.parse_args(argv)
    if args.feature == "audio":
        from . import hostaudio
        system = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(platform.system(), "unknown")
        return hostaudio.serve(args, system)
    try:
        server = _Server((args.bind, args.port), args.trace)
    except OSError as error:
        print(json.dumps({"error": "cannot listen on %s:%d: %s" % (args.bind, args.port, error)}), flush=True)
        return 1
    info = dict(FEATURES[args.feature], feature=args.feature, bind=args.bind, port=server.server_address[1],
                pid=os.getpid())
    print(json.dumps(info), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
