# One of the vendor layer's hardware-facing components for tvemu-arm64-rdke.
# The source is the Raspberry Pi 4's (rdk-gstreamer-utils-raspberrypi, release 1.2.1): it is
# written for Linux' own interfaces, not for Broadcom's, and what in it is the
# Pi's is replaced here. rdke/README.md says what each component does in the VM.
SUMMARY = "RDK's GStreamer utilities, the platform's part: what the players ask about decoders and sinks"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=86d3f3a95c324c9479bd8986968f4327"

DEPENDS += "gstreamer1.0 gstreamer1.0-plugins-base rdk-gstreamer-utils-headers"

SRC_URI = "git://github.com/rdkcentral/rdk-gstreamer-utils-raspberrypi;protocol=https;nobranch=1"
SRCREV = "604ba60f49e8bf5e9b19baf2381486ddbf21a9fe"
PV = "1.2.1"
S = "${WORKDIR}/git"

PROVIDES = "virtual/vendor-rdk-gstreamer-utils-platform"
RPROVIDES:${PN} = "virtual/vendor-rdk-gstreamer-utils-platform"

CXXFLAGS += "-I${STAGING_INCDIR}/glib-2.0 -I${STAGING_INCDIR}/gstreamer-1.0 -I${STAGING_DIR_TARGET}/${libdir}/glib-2.0/include/ "

inherit autotools pkgconfig tvemu-hal-version

CXXFLAGS += " \
  -DRDK_HALIF_RDK_GSTREAMER_VERSION_MAJOR=${RDK_GSTREAMER_VER_MAJOR} \
  -DRDK_HALIF_RDK_GSTREAMER_VERSION_MINOR=${RDK_GSTREAMER_VER_MINOR} \
  -DRDK_HALIF_RDK_GSTREAMER_VERSION_BUILD=${RDK_GSTREAMER_VER_BUILD} \
  -DRDK_HALIF_RDK_GSTREAMER_VERSION_ENGINEERING=${RDK_GSTREAMER_VER_ENG}"

do_configure[noexec] = "1"

do_compile () {
    oe_runmake -C ${S} -f Makefile
}

do_install() {
    install -d ${D}/${libdir}
    install -m 0755 ${S}/librdkgstreamerutilsplatform.so ${D}/${libdir}
}

INSANE_SKIP:${PN} = "dev-so ldflags textrel"
FILES_SOLIBSDEV = ""
FILES:${PN} += "${libdir}/*.so"
