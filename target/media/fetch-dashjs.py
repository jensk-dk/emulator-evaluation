#!/usr/bin/env python3
"""Fetches dash.js, the player library of the STB simulator's video on demand
application, for the target image. Used by target/Dockerfile.

    fetch-dashjs.py PACKAGE_URL VERSION SHA256 OUTPUT_DIR

The release is the package that the dash.js project publishes on the npm
registry, at one version: target/image.json names it, with the SHA-256 of the
package, which is checked before anything is taken from it. The output
directory gets the player (the minified build with all of its parts), its
licence (BSD 3-Clause), and a file with the version.
"""
import hashlib
import io
import os
import sys
import tarfile
import time
import urllib.request

FILES = {"package/dist/modern/umd/dash.all.min.js": "dash.all.min.js", "package/LICENSE.md": "LICENSE.md"}


def main():
    if len(sys.argv) != 5:
        sys.exit(__doc__.strip())
    URL, VERSION, SHA256, out = sys.argv[1:]
    data = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(URL, timeout=120) as reply:
                data = reply.read()
            break
        except OSError as error:
            print("fetch-dashjs: %s (attempt %d)" % (error, attempt + 1), file=sys.stderr)
            time.sleep(5)
    if data is None:
        sys.exit("fetch-dashjs: could not fetch %s" % URL)
    found = hashlib.sha256(data).hexdigest()
    if found != SHA256:
        sys.exit("fetch-dashjs: %s has SHA-256 %s, not the expected %s" % (URL, found, SHA256))
    os.makedirs(out, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member, name in FILES.items():
            with archive.extractfile(member) as source, open(os.path.join(out, name), "wb") as target:
                target.write(source.read())
    with open(os.path.join(out, "dash.version"), "w") as handle:
        handle.write(VERSION + "\n")
    print("fetch-dashjs: dash.js %s" % VERSION)


if __name__ == "__main__":
    main()
