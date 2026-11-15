"""A client of the remote framebuffer protocol (RFB, the protocol of VNC) that
follows a display: the launcher's window gets the target's display with it.

Two servers are on the other end: QEMU's own (VM mode), and emuscreen in the
target (container mode, target/src/emuscreen.c). Both are asked for the same
thing: no authentication, pixels as four bytes (blue, green, red, unused), raw
encoding, and word of a change of the display's size.

    client = Client(address, on_size, on_update, on_state)
    client.start()          # a thread; it connects, and connects again
    ...
    client.close()

`address` is a socket path or a (host, port) pair. The callbacks run on the
client's thread:

    on_size(width, height)              the display's size, at first and when it changes
    on_update(x, y, width, height, pixels)
                                        a rectangle of new pixels (a bytearray)
    on_state(text)                      what the client is doing, for a person

After on_update the client waits for `shown()` before it asks the server for
more, so a viewer that draws slower than the display changes is not flooded.
"""
import socket
import struct
import threading
import time

RAW = 0
DESKTOP_SIZE = -223
# Pixels as four bytes: blue, green, red, unused.
PIXEL_FORMAT = struct.pack(">BxxxBBBBHHHBBBxxx", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)


class Closed(Exception):
    """The server ended the connection, or the client was closed."""


class Client(threading.Thread):
    def __init__(self, address, on_size, on_update, on_state=None):
        super().__init__(daemon=True)
        self.address = address
        self.on_size = on_size
        self.on_update = on_update
        self.on_state = on_state or (lambda text: None)
        self.connected = False
        self.size = None
        self.updates = 0
        self._connection = None
        self._closing = False
        self._shown = threading.Event()

    def shown(self):
        """The viewer has drawn the last update; the next may be asked for."""
        self._shown.set()

    def close(self):
        self._closing = True
        self._shown.set()
        connection = self._connection
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    # ------------------------------------------------------------------

    def run(self):
        waited = False
        while not self._closing:
            try:
                self._connection = self._connect()
            except OSError:
                if not waited:
                    self.on_state("waiting for the target's display")
                    waited = True
                time.sleep(0.2)
                continue
            try:
                self._follow(self._connection)
            except (OSError, Closed, struct.error):
                pass
            finally:
                self.connected = False
                try:
                    self._connection.close()
                except OSError:
                    pass
                self._connection = None
            if not self._closing:
                # The display service in the target was stopped (a workload
                # starts it anew for each test), or the emulator ended.
                self.on_state("the target's display is off")
                waited = True
                time.sleep(0.2)

    def _connect(self):
        if isinstance(self.address, tuple):
            connection = socket.create_connection(self.address, timeout=10)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        else:
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.settimeout(10)
            connection.connect(self.address)
        return connection

    def _receive(self, connection, count):
        data = bytearray(count)
        view = memoryview(data)
        got = 0
        while got < count:
            read = connection.recv_into(view[got:], count - got)
            if not read:
                raise Closed()
            got += read
        return data

    def _follow(self, connection):
        receive = lambda count: self._receive(connection, count)
        # A published port of a container answers before the server behind it
        # does: a connection that says nothing is tried again.
        connection.settimeout(5)
        receive(12)                                         # the server's protocol version
        connection.sendall(b"RFB 003.008\n")
        kinds = receive(1)[0]
        if kinds == 0:
            raise Closed()
        if 1 not in receive(kinds):                         # 1: no authentication
            raise Closed()
        connection.sendall(b"\x01")
        if bytes(receive(4)) != b"\0\0\0\0":
            raise Closed()
        connection.sendall(b"\x01")                         # share the display with other clients
        width, height = struct.unpack(">HH", receive(20)[:4])
        receive(struct.unpack(">I", receive(4))[0])         # the display's name
        connection.sendall(PIXEL_FORMAT)
        connection.sendall(struct.pack(">BxHii", 2, 2, RAW, DESKTOP_SIZE))
        connection.settimeout(None)
        self.connected = True
        self._resize(width, height)
        self.on_state("")
        incremental = 0
        while not self._closing:
            width, height = self.size
            connection.sendall(struct.pack(">BBHHHH", 3, incremental, 0, 0, width, height))
            incremental = 1
            # Until the server has sent pixels or a new size (it sends other
            # things in between).
            result = None
            while not result:
                if self._closing:
                    return
                result = self._update(connection, receive)
            if result == "resized":
                incremental = 0         # all of the display at its new size
            elif result == "empty":
                time.sleep(0.005)       # an answer without pixels: ask again, but not in a tight loop
            self._shown.wait()
            self._shown.clear()

    def _resize(self, width, height):
        if self.size != (width, height):
            self.size = (width, height)
            self.on_size(width, height)

    def _update(self, connection, receive):
        """Take one message from the server. Returns "drawn" when it had
        pixels, "resized" when it had a new size instead and "empty" when it
        had neither, after each of which the next request is due; None for a
        message that is no answer to a request."""
        kind = receive(1)[0]
        if kind == 2:                                       # bell
            return None
        if kind == 3:                                       # text from the server's clipboard
            receive(struct.unpack(">xxxI", receive(7))[0])
            return None
        if kind != 0:
            raise Closed()
        drawn = False
        resized = False
        for _ in range(struct.unpack(">xH", receive(3))[0]):
            x, y, width, height, encoding = struct.unpack(">HHHHi", receive(12))
            if encoding == DESKTOP_SIZE:
                self._resize(width, height)
                resized = True
            elif encoding == RAW:
                if width and height:
                    self.on_update(x, y, width, height, receive(width * height * 4))
                    drawn = True
            else:
                raise Closed()
        if drawn and not resized:
            self.updates += 1
            return "drawn"
        # Nothing the viewer has to show first.
        self._shown.set()
        return "resized" if resized else "empty"
