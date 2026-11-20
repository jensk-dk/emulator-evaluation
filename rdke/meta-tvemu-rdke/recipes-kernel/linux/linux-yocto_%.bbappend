# The kernel of tvemu-arm64-rdke: openembedded-core's kernel for qemuarm64,
# with what RDK-E expects of a kernel and what tv-emu's VM has as devices.

FILESEXTRAPATHS:prepend:tvemu := "${THISDIR}/files:"

# qemuarm64's kernel configuration is the base.
COMPATIBLE_MACHINE:tvemu = "tvemu-arm64-rdke"
KMACHINE:tvemu = "qemuarm64"

SRC_URI:append:tvemu = " \
    file://tvemu-virt.cfg \
    file://rdke-android.cfg \
    file://rdke.cfg \
    file://rdke-apparmor.cfg \
"
