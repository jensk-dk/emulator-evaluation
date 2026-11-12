"""Reads the images the launcher captures from the emulator's display, and
writes the ones it has to put together itself.

Standard library only: binary PPM (what QEMU's screendump writes) and 8-bit
RGB or RGBA PNG without interlacing (what the target's compositor writes).
"""
import struct
import zlib

from .errors import EmuError

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class Image:
    def __init__(self, width, height, channels, data):
        self.width = width
        self.height = height
        self._channels = channels
        self._data = data

    def pixel(self, x, y):
        """(red, green, blue) at column x, row y, counted from the top left."""
        offset = (y * self.width + x) * self._channels
        return tuple(self._data[offset:offset + 3])


def _ppm_header(data):
    """Returns (width, height, offset of the pixel data)."""
    fields = []
    position = 0
    while len(fields) < 4:
        while data[position:position + 1].isspace():
            position += 1
        if data[position:position + 1] == b"#":
            position = data.index(b"\n", position) + 1
            continue
        end = position
        while end < len(data) and not data[end:end + 1].isspace():
            end += 1
        fields.append(data[position:end])
        position = end
    if fields[0] != b"P6" or fields[3] != b"255":
        raise EmuError("not an 8-bit binary PPM image")
    return int(fields[1]), int(fields[2]), position + 1


def _png_chunks(data):
    position = len(_PNG_SIGNATURE)
    while position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        yield kind, data[position + 8:position + 8 + length]
        position += 12 + length


def _png_header(data):
    for kind, body in _png_chunks(data):
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or color not in (2, 6) or interlace:
                raise EmuError("unsupported PNG variant (bit depth %d, colour type %d, interlace %d)"
                               % (depth, color, interlace))
            return width, height, 3 if color == 2 else 4
    raise EmuError("PNG image without a header")


def size(path):
    """(width, height) of an image, read from its header only."""
    with open(path, "rb") as handle:
        head = handle.read(4096)
    if head.startswith(_PNG_SIGNATURE):
        return _png_header(head)[:2]
    if head.startswith(b"P6"):
        return _ppm_header(head)[:2]
    raise EmuError("%s is neither a PNG nor a PPM image" % path)


def _png_pixels(data):
    width, height, channels = _png_header(data)
    raw = zlib.decompress(b"".join(body for kind, body in _png_chunks(data) if kind == b"IDAT"))
    stride = width * channels
    out = bytearray(stride * height)
    previous = bytes(stride)
    for row in range(height):
        start = row * (stride + 1)
        kind = raw[start]
        line = bytearray(raw[start + 1:start + 1 + stride])
        if kind == 1:       # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif kind == 2:     # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 255
        elif kind == 3:     # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 255
        elif kind == 4:     # Paeth
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = previous[i]
                corner = previous[i - channels] if i >= channels else 0
                estimate = left + up - corner
                near_left, near_up, near_corner = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
                if near_left <= near_up and near_left <= near_corner:
                    line[i] = (line[i] + left) & 255
                elif near_up <= near_corner:
                    line[i] = (line[i] + up) & 255
                else:
                    line[i] = (line[i] + corner) & 255
        elif kind != 0:
            raise EmuError("corrupt PNG image (filter type %d)" % kind)
        out[row * stride:(row + 1) * stride] = line
        previous = line
    return Image(width, height, channels, bytes(out))


def save(path, width, height, rgb, image_format):
    """Write 8-bit RGB pixels, rows from the top, as "ppm" or "png"."""
    if image_format == "ppm":
        data = b"P6\n%d %d\n255\n" % (width, height) + bytes(rgb)
    elif image_format == "png":
        stride = width * 3
        rows = b"".join(b"\0" + bytes(rgb[row * stride:(row + 1) * stride]) for row in range(height))
        data = _PNG_SIGNATURE
        for kind, body in ((b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
                           (b"IDAT", zlib.compress(rows, 6)), (b"IEND", b"")):
            data += struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    else:
        raise EmuError("unknown image format %r" % image_format)
    with open(path, "wb") as handle:
        handle.write(data)


def load(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if data.startswith(_PNG_SIGNATURE):
        return _png_pixels(data)
    if data.startswith(b"P6"):
        width, height, offset = _ppm_header(data)
        return Image(width, height, 3, data[offset:offset + width * height * 3])
    raise EmuError("%s is neither a PNG nor a PPM image" % path)
