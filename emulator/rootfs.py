"""The root file systems the launcher can start a target from.

"debian" is the evaluation's own image, which the launcher builds from
target/ and which has the workloads, the driver features and the STB
simulator. "rdke" is an RDK-E image built with Yocto for the machine
tvemu-arm64-rdke (rdke/README.md): the launcher does not build it, it boots
the files it finds, and the target then runs its own software."""
import pathlib

from .errors import EmuError
from .paths import BUILD_DIR, ROOT

DEBIAN = "debian"
RDKE = "rdke"
CHOICES = (DEBIAN, RDKE)
DEFAULT = DEBIAN

# The one guest CPU architecture the RDK-E machine is defined for.
RDKE_ARCH = "arm64"
# Where its files are looked for, and the option that names another place.
RDKE_DIR_OPTION = "rdke-dir"
RDKE_README = "rdke/README.md"
# The names a file may have: Yocto's own first, then the Debian image's.
RDKE_KERNEL = ("Image", "vmlinuz")
RDKE_ROOT = ("rootfs.ext4", "rootfs.img")
RDKE_INITRD = ("initrd.img",)       # optional: Yocto's kernel for the machine needs none


def rdke_dir(options=None):
    named = (options or {}).get(RDKE_DIR_OPTION)
    return pathlib.Path(named).expanduser() if named else BUILD_DIR / RDKE / RDKE_ARCH


def _first(directory, names):
    for name in names:
        if (directory / name).is_file():
            return directory / name
    return None


def rdke_files(options=None):
    """The kernel, the root file system and the initial RAM disk (or None) of
    the RDK-E image; raises EmuError when the image is not there."""
    directory = rdke_dir(options)
    kernel, root = _first(directory, RDKE_KERNEL), _first(directory, RDKE_ROOT)
    if not kernel or not root:
        missing = ["%s (%s)" % (what, " or ".join(names)) for what, found, names in (
            ("kernel", kernel, RDKE_KERNEL), ("root file system", root, RDKE_ROOT)) if not found]
        raise EmuError("no RDK-E image in %s: it has no %s" % (directory, " and no ".join(missing)),
                       hint="the launcher does not build the RDK-E root file system; %s says how it is built with "
                            "Yocto and which files go there (--option %s=DIR names another directory)"
                            % (RDKE_README, RDKE_DIR_OPTION))
    return {"directory": directory, "kernel": kernel, "root": root, "initrd": _first(directory, RDKE_INITRD)}


def rdke_state(options=None):
    """One line for "emu doctor" and "emu build": whether the image is there."""
    try:
        files = rdke_files(options)
    except EmuError as error:
        return False, str(error)
    where = files["directory"]
    try:
        where = where.resolve().relative_to(ROOT)       # as the documents name it
    except ValueError:
        pass
    return True, "%s and %s in %s%s" % (files["kernel"].name, files["root"].name, where,
                                        ", with %s" % files["initrd"].name if files["initrd"] else "")
