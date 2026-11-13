#!/usr/bin/env python3
"""Split a fragmented MP4 file into the pieces an MSE player is fed: the
initialisation segment (everything before the first fragment) and one file
per media fragment (a moof box with the mdat that follows it).

    split-fragments.py INPUT.fmp4 OUTPUT_DIR
"""
import os
import struct
import sys


def boxes(data):
    offset = 0
    while offset + 8 <= len(data):
        size, kind = struct.unpack(">I4s", data[offset:offset + 8])
        if size == 1:
            size = struct.unpack(">Q", data[offset + 8:offset + 16])[0]
        elif size == 0:
            size = len(data) - offset
        yield kind.decode("latin-1"), offset, size
        offset += size


def main():
    source, out = sys.argv[1], sys.argv[2]
    with open(source, "rb") as handle:
        data = handle.read()
    os.makedirs(out, exist_ok=True)
    found = list(boxes(data))
    first = next(offset for kind, offset, _ in found if kind == "moof")
    with open(os.path.join(out, "init.mp4"), "wb") as handle:
        handle.write(data[:first])
    count = 0
    start = None
    for kind, offset, size in found:
        if kind == "moof":
            start = offset
        elif kind == "mdat" and start is not None:
            count += 1
            with open(os.path.join(out, "fragment-%03d.m4s" % count), "wb") as handle:
                handle.write(data[start:offset + size])
            start = None
    if not count:
        sys.exit("split-fragments: %s has no media fragments" % source)


if __name__ == "__main__":
    main()
