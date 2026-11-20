SUMMARY = "The emulator's remote control as an input device of the target"
DESCRIPTION = "Takes the remote control keys that tv-emu's display window sends over a virtio serial port \
and gives them to the kernel as the key events of a keyboard (uinput), for a compositor to read."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://tvemu-remote.c file://tvemu-remote.service"
S = "${WORKDIR}"

inherit systemd

SYSTEMD_SERVICE:${PN} = "tvemu-remote.service"

do_compile() {
    ${CC} ${CFLAGS} ${LDFLAGS} -Wall -o tvemu-remote tvemu-remote.c
}

do_install() {
    install -D -m 0755 tvemu-remote ${D}${bindir}/tvemu-remote
    install -D -m 0644 ${WORKDIR}/tvemu-remote.service ${D}${systemd_system_unitdir}/tvemu-remote.service
}

FILES:${PN} += "${systemd_system_unitdir}"
