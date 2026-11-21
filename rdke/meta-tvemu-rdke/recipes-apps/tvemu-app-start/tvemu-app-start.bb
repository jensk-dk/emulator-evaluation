SUMMARY = "Shows a page in one of the browser's Thunder plug-ins, through RDK's window manager"
DESCRIPTION = "A command, tvemu-app-start CALLSIGN URL: a display from org.rdk.RDKWindowManager, the \
plug-in started on it with the page, and the focus. It stands in for the launch method of org.rdk.RDKShell, \
which RDK's own start script for its user interface still calls and which this middleware no longer has."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://tvemu-app-start"
S = "${WORKDIR}"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${WORKDIR}/tvemu-app-start ${D}${bindir}/tvemu-app-start
}

RDEPENDS:${PN} = "curl webkitbrowser-plugin"
