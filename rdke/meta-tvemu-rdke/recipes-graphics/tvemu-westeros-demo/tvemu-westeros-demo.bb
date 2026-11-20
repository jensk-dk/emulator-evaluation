SUMMARY = "Starts Westeros on the VM's display, and Westeros' own test client"
DESCRIPTION = "Stands in for RDK-E's window manager, which starts Westeros on a device and which this image \
does not have: a systemd unit that starts the compositor at boot on the DRM device, and one for westeros_test."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://tvemu-westeros.service file://tvemu-westeros-client.service"
S = "${WORKDIR}"

inherit systemd

SYSTEMD_SERVICE:${PN} = "tvemu-westeros.service tvemu-westeros-client.service"

do_install() {
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/tvemu-westeros.service ${WORKDIR}/tvemu-westeros-client.service ${D}${systemd_system_unitdir}/
}

FILES:${PN} += "${systemd_system_unitdir}"
RDEPENDS:${PN} = "westeros westeros-soc-drm"
