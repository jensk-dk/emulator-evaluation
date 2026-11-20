# One of the vendor layer's hardware-facing components for tvemu-arm64-rdke.
# The source is the Raspberry Pi 4's (rdkvhal-power-manager-raspberrypi4, release 1.2.1): it is
# written for Linux' own interfaces, not for Broadcom's, and what in it is the
# Pi's is replaced here. rdke/README.md says what each component does in the VM.
SUMMARY = "Power manager: the power state the middleware sets, kept in the target"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=b1e01b26bacfc2232046c90a330332b3"

PROVIDES = "virtual/pwrmgr-hal virtual/vendor-pwrmgr-hal"
RPROVIDES:${PN} = "virtual/pwrmgr-hal virtual/vendor-pwrmgr-hal"

SRC_URI = "git://github.com/rdkcentral/rdkvhal-power-manager-raspberrypi4;protocol=https;nobranch=1"
SRCREV = "196f7e4c10d23e29182558b843bdfdb61030e07a"
PV = "1.2.1"
S = "${WORKDIR}/git"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += "file://0001-tvemu-temperature.patch"
RDEPENDS:${PN} += "tvemu-device"

# The IARM bus' headers: from the interface headers' package in a vendor
# layer's own build, as on the Pi. In one build with the middleware they come
# with the bus itself, which has the same files; with both, a recipe that
# needs this component and the bus finds the files twice and stops.
TVEMU_IARMBUS_HEADERS = "${@'iarmbus' if d.getVar('LAYER_NAME') == 'MIDDLEWARE' else 'iarmbus-headers'}"
DEPENDS = "power-manager-headers ${TVEMU_IARMBUS_HEADERS}"

inherit autotools

CFLAGS += " -I${STAGING_DIR_TARGET}${includedir}/rdk/halif/power-manager/"

FILES:${PN} += "${libdir}/*.so"
FILES_SOLIBSDEV = ""
INSANE_SKIP:${PN} += "dev-so"
