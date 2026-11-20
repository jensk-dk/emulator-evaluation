SUMMARY = "Starts Weston on the VM's display, and a client that draws in it"
DESCRIPTION = "Stands in for what RDK-E's window manager does with Westeros, which this image does not have: \
a systemd unit that starts the compositor at boot as root on the DRM device, and one for a test client."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://tvemu-weston.service file://tvemu-wayland-client.service file://weston.ini"
S = "${WORKDIR}"

inherit systemd

SYSTEMD_SERVICE:${PN} = "tvemu-weston.service tvemu-wayland-client.service"

do_install() {
    install -d ${D}${systemd_system_unitdir} ${D}${sysconfdir}/xdg/weston
    install -m 0644 ${WORKDIR}/tvemu-weston.service ${WORKDIR}/tvemu-wayland-client.service ${D}${systemd_system_unitdir}/
    install -m 0644 ${WORKDIR}/weston.ini ${D}${sysconfdir}/xdg/weston/weston.ini
}

FILES:${PN} += "${systemd_system_unitdir} ${sysconfdir}/xdg/weston"
RDEPENDS:${PN} = "weston weston-examples"
