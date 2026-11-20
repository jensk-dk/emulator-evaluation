# The vendor layer's part of RDK-E's system integration for tvemu-arm64-rdke:
# what the middleware's start-up expects a device to bring. The source is the
# Raspberry Pi 4's (rdkvhal-sysint-raspberrypi4, release 1.1.22); the device's
# properties and the settings of Thunder's process are this machine's own, and
# the Pi's Bluetooth reset is left out.
SUMMARY = "System integration, the vendor's part: device properties, start-up units and key map"
SECTION = "console/utils"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=b1e01b26bacfc2232046c90a330332b3"

SRC_URI = "git://github.com/rdkcentral/rdkvhal-sysint-raspberrypi4;protocol=https;nobranch=1 \
           file://device-vendor.properties \
           file://00-wpeframework-vendor.conf \
           "
SRCREV = "1ea276103df0a227e95545bcfe27e3811787fafa"
PV = "1.1.22"
S = "${WORKDIR}/git"

inherit systemd

RDEPENDS:${PN} += "util-linux-uuidgen tvemu-device"

do_compile[noexec] = "1"

SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install() {
    install -d ${D}${systemd_unitdir}/system ${D}${bindir} ${D}${sysconfdir}

    # Thunder's process: the VM's display.
    install -D -m 0644 ${WORKDIR}/00-wpeframework-vendor.conf ${D}${systemd_unitdir}/system/wpeframework.service.d/00-wpeframework-vendor.conf
    # The device settings manager starts after RDK's window manager, as on the Pi.
    install -D -m 0644 ${S}/systemd_units/00-dsmgr-vendor.conf ${D}${systemd_unitdir}/system/dsmgr.service.d/00-dsmgr-vendor.conf

    install -m 0644 ${S}/systemd_units/oem-first-boot.service ${D}${systemd_unitdir}/system/oem-first-boot.service
    install -m 0755 ${S}/scripts/oem-first-boot.sh ${D}${bindir}/oem-first-boot.sh
    install -m 0644 ${S}/systemd_units/enable-transition-markers.service ${D}${systemd_unitdir}/system/enable-transition-markers.service
    install -m 0755 ${S}/scripts/enable-transition-markers.sh ${D}${bindir}/enable-transition-markers.sh
    # The middleware's start-up waits for a unit of this name; like the Pi,
    # the VM has no non-volatile memory to prepare.
    install -m 0644 ${S}/systemd_units/nvram.service ${D}${systemd_unitdir}/system/nvram.service

    install -D -m 0644 ${S}/systemd_units/00-dropbear-vendor.conf ${D}${systemd_unitdir}/system/dropbear.service.d/00-dropbear.conf
    install -D -m 0644 ${S}/systemd_units/00-remove-static-ssh-drop-config.conf ${D}${systemd_unitdir}/system/iptables.service.d/00-remove-static-ssh-drop-config.conf
    install -m 0644 ${S}/dropbear/sshbanner.txt ${D}${sysconfdir}

    # The device's properties, with the build's values where it has them.
    install -m 0644 ${WORKDIR}/device-vendor.properties ${D}${sysconfdir}/device-vendor.properties
    for pair in "MODEL_NUM=${DEVICE_MODEL_NUMBER}" "DAC_APP_PATH=${DAC_APP_PATH}" \
                "APP_PREINSTALL_DIRECTORY=${APP_PREINSTALL_DIRECTORY}" "APP_DOWNLOAD_DIRECTORY=${APP_DOWNLOAD_DIRECTORY}" \
                "DEFAULT_APP_STORAGE_PATH=${DEFAULT_APP_STORAGE_PATH}"; do
        key=${pair%%=*}
        value=${pair#*=}
        [ -n "$value" ] && sed -i "s|^$key=.*|$key=$value|" ${D}${sysconfdir}/device-vendor.properties
    done

    # The remote control's configuration and key map, as the Pi has them: the
    # key map takes Linux key codes, which the emulator's remote control sends.
    install -D -m 0644 ${S}/etc/rdk-bt-rcu-config.json ${D}${sysconfdir}/vendor/input/ctrlm_config.json
    install -D -m 0755 ${S}/scripts/device-specific-reset.sh ${D}/lib/rdk/device-specific-reset.sh
    if [ -n "${WINDOWMANAGER_RCU_KEYMAP_FILE}" ]; then
        install -D -m 0644 ${S}/etc/generic_rcu_keymapping.json ${D}${WINDOWMANAGER_RCU_KEYMAP_FILE}
    fi
}

FILES:${PN} += "${systemd_unitdir}/system/* ${sysconfdir}/* /lib/rdk/device-specific-reset.sh"

SYSTEMD_SERVICE:${PN} += "oem-first-boot.service nvram.service enable-transition-markers.service"
