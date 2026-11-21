SUMMARY = "A stand-in for org.rdk.RDKShell on RDK-E's middleware"
DESCRIPTION = "A Thunder plug-in under the call sign org.rdk.RDKShell, which RDK-E's middleware no longer \
has: org.rdk.RDKWindowManager has taken its place, and applications are meant to be started by \
org.rdk.AppManager. RDK's reference user interface up to its 5.x releases still starts every application \
with org.rdk.RDKShell. This plug-in answers the calls that user interface makes, with the window manager \
and the applications' own plug-ins, so that its web applications start and end (files/RDKShell.cpp)."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://CMakeLists.txt \
           file://Module.h \
           file://Module.cpp \
           file://RDKShell.cpp \
           file://org.rdk.RDKShell.json \
           file://wpeframework-rdkshell.service \
           "
S = "${WORKDIR}"

inherit cmake pkgconfig systemd

SYSTEMD_SERVICE:${PN} = "wpeframework-rdkshell.service"

PACKAGE_ARCH = "${MIDDLEWARE_ARCH}"
TOOLCHAIN = "gcc"

DEPENDS = "wpeframework wpeframework-tools-native entservices-apis"
RDEPENDS:${PN} = "wpeframework curl"

EXTRA_OECMAKE += "-DBUILD_REFERENCE=${PV} -DBUILD_SHARED_LIBS=ON"
CXXFLAGS += "-Wall -Werror"

do_install:append() {
    install -d ${D}${sysconfdir}/WPEFramework/plugins
    install -m 0644 ${WORKDIR}/org.rdk.RDKShell.json ${D}${sysconfdir}/WPEFramework/plugins/
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/wpeframework-rdkshell.service ${D}${systemd_system_unitdir}/
}

FILES_SOLIBSDEV = ""
FILES:${PN} += "${libdir}/wpeframework/plugins/*.so ${sysconfdir}/WPEFramework/plugins ${systemd_system_unitdir}"
INSANE_SKIP:${PN} += "libdir dev-so"
INSANE_SKIP:${PN}-dbg += "libdir"
