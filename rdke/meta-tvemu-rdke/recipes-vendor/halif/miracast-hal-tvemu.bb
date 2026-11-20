# One of the vendor layer's hardware-facing components for tvemu-arm64-rdke.
# The source is the Raspberry Pi 4's (rdkvhal-miracast-raspberrypi4, release 1.0.2): it is
# written for Linux' own interfaces, not for Broadcom's, and what in it is the
# Pi's is replaced here. rdke/README.md says what each component does in the VM.
SUMMARY = "Miracast: the player side of receiving a Wi-Fi display stream, on GStreamer"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=86d3f3a95c324c9479bd8986968f4327"

SRC_URI = "git://github.com/rdkcentral/rdkvhal-miracast-raspberrypi4;protocol=https;nobranch=1"
SRCREV = "c8888aeb55c7822a1010dc5ed8fcb74fd2737de3"
PV = "1.0.2"
S = "${WORKDIR}/git"

PROVIDES = "virtual/vendor-miracast-soc"
RPROVIDES:${PN} = "virtual/vendor-miracast-soc"

inherit pkgconfig cmake

DEPENDS = "gstreamer1.0 gstreamer1.0-plugins-base"
RDEPENDS:${PN} = "gstreamer1.0 gstreamer1.0-plugins-base"
AUTO_LIBNAME_PKGS = ""
