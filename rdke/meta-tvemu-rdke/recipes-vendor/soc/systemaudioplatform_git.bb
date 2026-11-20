# One of the vendor layer's hardware-facing components for tvemu-arm64-rdke.
# The source is the Raspberry Pi 4's (rdkvhal-systemaudioplatform-raspberrypi4, release 1.0.2): it is
# written for Linux' own interfaces, not for Broadcom's, and what in it is the
# Pi's is replaced here. rdke/README.md says what each component does in the VM.
SUMMARY = "System audio: the platform side of playing system sounds, on GStreamer"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://../LICENSE;md5=86d3f3a95c324c9479bd8986968f4327"

DEPENDS += "gstreamer1.0 gstreamer1.0-plugins-base"

PROVIDES += "virtual/vendor-systemaudioplatform"
RPROVIDES:${PN} = "virtual/vendor-systemaudioplatform"

SRC_URI = "git://github.com/rdkcentral/rdkvhal-systemaudioplatform-raspberrypi4;protocol=https;nobranch=1"
SRCREV = "25306950e12177de4673590647366dbb5f3f4741"
PV = "1.0.2"
S = "${WORKDIR}/git/systemaudioplatform"

inherit cmake pkgconfig

FILES:${PN} = "/usr/lib/libsystemaudioplatform.so.*"
FILES:${PN}-dev = "/usr/lib/libsystemaudioplatform.so /usr/include/systemaudioplatform.h"
