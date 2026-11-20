# One of the vendor layer's hardware-facing components for tvemu-arm64-rdke.
# The source is the Raspberry Pi 4's (rdkvhal-deepsleep-manager-raspberrypi4, release 1.1.1): it is
# written for Linux' own interfaces, not for Broadcom's, and what in it is the
# Pi's is replaced here. rdke/README.md says what each component does in the VM.
SUMMARY = "Deep sleep: entering it and waking from it"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=b1e01b26bacfc2232046c90a330332b3"

PROVIDES = "virtual/deepsleep-hal virtual/vendor-deepsleep-hal virtual/vendor-deepsleepmgr-hal"
RPROVIDES:${PN} = "virtual/deepsleep-hal virtual/vendor-deepsleep-hal virtual/vendor-deepsleepmgr-hal"

SRC_URI = "git://github.com/rdkcentral/rdkvhal-deepsleep-manager-raspberrypi4;protocol=https;nobranch=1"
SRCREV = "ec8daff3e857f1b0aadb11708c1637718ec6af64"
PV = "1.1.1"
S = "${WORKDIR}/git"

# The IARM bus' headers: from the interface headers' package in a vendor
# layer's own build, as on the Pi. In one build with the middleware they come
# with the bus itself, which has the same files; with both, a recipe that
# needs this component and the bus finds the files twice and stops.
TVEMU_IARMBUS_HEADERS = "${@'iarmbus' if d.getVar('LAYER_NAME') == 'MIDDLEWARE' else 'iarmbus-headers'}"
DEPENDS = "deepsleep-manager-headers ${TVEMU_IARMBUS_HEADERS}"

inherit autotools

CFLAGS += " -I${STAGING_DIR_TARGET}${includedir}/rdk/halif/deepsleep-manager/"

FILES:${PN} += "${libdir}/*.so"
FILES_SOLIBSDEV = ""
INSANE_SKIP:${PN} += "dev-so"
