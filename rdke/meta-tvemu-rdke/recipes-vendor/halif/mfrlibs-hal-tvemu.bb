# One of the vendor layer's hardware-facing components for tvemu-arm64-rdke.
# The source is the Raspberry Pi 4's (rdkvhal-mfrlibs-raspberrypi4, release 1.2.0): it is
# written for Linux' own interfaces, not for Broadcom's, and what in it is the
# Pi's is replaced here. rdke/README.md says what each component does in the VM.
SUMMARY = "Manufacturer data: the identity of the virtual device"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=175792518e4ac015ab6696d16c4f607e"

# The IARM bus' headers: from the interface headers' package in a vendor
# layer's own build, as on the Pi. In one build with the middleware they come
# with the bus itself, which has the same files; with both, a recipe that
# needs this component and the bus finds the files twice and stops.
TVEMU_IARMBUS_HEADERS = "${@'iarmbus' if d.getVar('LAYER_NAME') == 'MIDDLEWARE' else 'iarmbus-headers'}"
DEPENDS = "iarmmgrs-hal-headers ${TVEMU_IARMBUS_HEADERS}"

SRC_URI = "git://github.com/rdkcentral/rdkvhal-mfrlibs-raspberrypi4;protocol=https;nobranch=1"
SRCREV = "c3ac871baa83bfe9aa81df78d0cc8ef1e7774973"
PV = "1.2.0"
S = "${WORKDIR}/git"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += "file://0001-tvemu-identity-and-temperature.patch"
RDEPENDS:${PN} += "tvemu-device"

PROVIDES = "virtual/mfrlib"
RPROVIDES:${PN} = "virtual/mfrlib"

EXTRA_OECONF += "--enable-thermalprotection"

inherit autotools

do_install:append() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/FlashApp.sh ${D}${bindir}/FlashApp.sh
    ln -sr ${D}${bindir}/FlashApp.sh ${D}${bindir}/FlashApp
}

FILES_SOLIBSDEV = ""
FILES:${PN} += "${libdir}/*.so ${bindir}/*"
INSANE_SKIP:${PN} += "dev-so"
