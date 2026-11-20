# One of the vendor layer's hardware-facing components for tvemu-arm64-rdke.
# The source is the Raspberry Pi 4's (rdkvhal-rdkservices-raspberrypi4, release 1.0.1): it is
# written for Linux' own interfaces, not for Broadcom's, and what in it is the
# Pi's is replaced here. rdke/README.md says what each component does in the VM.
SUMMARY = "Display information: what the VM's display says about itself, read through DRM"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://../LICENSE;md5=175792518e4ac015ab6696d16c4f607e"

inherit cmake pkgconfig

PROVIDES += "virtual/vendor-displayinfo-soc"
RPROVIDES:${PN} = "virtual/vendor-displayinfo-soc"

DEPENDS += "libdrm"
RDEPENDS:${PN} += "libdrm"

SRC_URI = "git://github.com/rdkcentral/rdkvhal-rdkservices-raspberrypi4;protocol=https;nobranch=1"
SRCREV = "3b9b8e9d89ae538a652458de3883b181814dcafd"
PV = "1.0.1"
S = "${WORKDIR}/git/DisplayInfo"

# The VM's one DRM device is virtio-gpu, card0; the source names the Pi's.
do_configure:prepend() {
    sed -i 's|#define DEFAULT_DEVICE "/dev/dri/card1"|#define DEFAULT_DEVICE "${DRI_DEVICE_NAME}"|' ${S}/SoC_abstraction.cpp
}

FILES_SOLIBSDEV = ""
SOLIBS = ".so"
INSANE_SKIP:${PN} += "dev-so"
ALLOW_EMPTY:${PN} = "1"
FILES:${PN} += "${libdir}/libdisplayinfo-soc.so ${libdir}/*.so"
