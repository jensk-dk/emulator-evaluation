# One of the vendor layer's hardware-facing components for tvemu-arm64-rdke.
# The source is the Raspberry Pi 4's (rdkvhal-hdmicec-raspberrypi4, release 1.2.3): it is
# written for Linux' own interfaces, not for Broadcom's, and what in it is the
# Pi's is replaced here. rdke/README.md says what each component does in the VM.
SUMMARY = "HDMI-CEC: Linux' CEC framework, which the VM's kernel has with a simulated HDMI link"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=86d3f3a95c324c9479bd8986968f4327"

SRC_URI = "git://github.com/rdkcentral/rdkvhal-hdmicec-raspberrypi4;protocol=https;nobranch=1"
SRCREV = "a0a48b9640ff2f875ce66bcee3c05b7b9f739c6e"
PV = "1.2.3"
S = "${WORKDIR}/git"

PROVIDES = "virtual/hdmicec-hal virtual/vendor-hdmicec-hal"
RPROVIDES:${PN} = "virtual/hdmicec-hal virtual/vendor-hdmicec-hal"

DEPENDS = "hdmicecheader"

inherit cmake

FILES:${PN} += "${libdir}/*.so"
FILES_SOLIBSDEV = ""
INSANE_SKIP:${PN} += "dev-so"
