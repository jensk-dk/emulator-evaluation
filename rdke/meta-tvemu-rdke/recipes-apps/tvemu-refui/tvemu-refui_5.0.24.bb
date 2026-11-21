SUMMARY = "RDK's reference user interface, started at boot on the virtual machine"
DESCRIPTION = "What the recipes residentui and rdkresidentapp of RDK-E's application layer \
(meta-application-rdke-dev) give a device, for an image built with the middleware's layers alone: the \
released user interface (rdke-refui, a Lightning application that the device's own web server serves), \
the web server's path to it, and a unit that shows it in the ResidentApp browser. RDK's unit calls \
org.rdk.RDKShell, which this middleware no longer has; this one uses tvemu-app-start."
HOMEPAGE = "https://github.com/rdkcentral/rdke-refui"
LICENSE = "Apache-2.0 & MIT & OFL-1.1 & CC0-1.0 & BitstreamVera"
LIC_FILES_CHKSUM = "file://${S}/LICENSE;md5=387be95ea3370b9ae768c395d4eeaeea"

SRC_URI = "https://github.com/rdkcentral/rdke-refui/releases/download/${PV}/refui-${PV}.tar.gz;subdir=refui-${PV} \
           file://tvemu-refui.service \
           file://tvemu-refui-docroot.conf \
           "
SRC_URI[sha256sum] = "b19c9092316cf908d16afa348a0346b3e349bbe8fa6b1ec688231bcc2d0a62b7"

S = "${WORKDIR}/refui-${PV}"

inherit systemd

SYSTEMD_SERVICE:${PN} = "tvemu-refui.service"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}/home/root/lxresui
    cp -r ${S}/* ${D}/home/root/lxresui/
    install -d ${D}${systemd_system_unitdir} ${D}${sysconfdir}/lighttpd.d
    install -m 0644 ${WORKDIR}/tvemu-refui.service ${D}${systemd_system_unitdir}/
    install -m 0644 ${WORKDIR}/tvemu-refui-docroot.conf ${D}${sysconfdir}/lighttpd.d/
}

FILES:${PN} += "/home/root/lxresui ${systemd_system_unitdir} ${sysconfdir}/lighttpd.d"
RDEPENDS:${PN} = "tvemu-app-start lighttpd"
INSANE_SKIP:${PN} += "file-rdeps"
