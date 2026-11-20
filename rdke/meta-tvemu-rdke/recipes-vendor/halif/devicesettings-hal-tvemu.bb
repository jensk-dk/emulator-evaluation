# One of the vendor layer's hardware-facing components for tvemu-arm64-rdke.
# The source is the Raspberry Pi 4's (rdkvhal-devicesettings-raspberrypi4, release 1.4.11): it is
# written for Linux' own interfaces, not for Broadcom's, and what in it is the
# Pi's is replaced here. rdke/README.md says what each component does in the VM.
SUMMARY = "Device settings: the VM's display, sound and front panel, as the middleware asks for them"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=175792518e4ac015ab6696d16c4f607e"

PROVIDES = "virtual/devicesettings-hal virtual/vendor-devicesettings-hal"
RPROVIDES:${PN} = "virtual/devicesettings-hal virtual/vendor-devicesettings-hal"
PACKAGE_ARCH = "${MACHINE_ARCH}"

SRC_URI = "git://github.com/rdkcentral/rdkvhal-devicesettings-raspberrypi4;protocol=https;nobranch=1"
SRCREV = "92137204d211cf3954d1fa4b1dcc2caa758b8659"
PV = "1.4.11"
S = "${WORKDIR}/git"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += "file://0001-tvemu-virtual-display-and-device-files.patch"
RDEPENDS:${PN} += "tvemu-device"

DEPENDS = "devicesettings-hal-headers virtual/egl alsa-lib libdrm"

# The VM's one DRM device is virtio-gpu, card0. (The Pi's display is card1.)
EXTRA_OECMAKE += "-DDRI_CARD=${DRI_DEVICE_NAME}"
EXTRA_OECMAKE += "-DLIBNAME=ds-hal"

inherit systemd cmake pkgconfig tvemu-hal-version

CFLAGS += " \
  -DRDK_HALIF_DEVICE_SETTINGS_VERSION_MAJOR=${DEVICE_SETTINGS_VER_MAJOR} \
  -DRDK_HALIF_DEVICE_SETTINGS_VERSION_MINOR=${DEVICE_SETTINGS_VER_MINOR} \
  -DRDK_HALIF_DEVICE_SETTINGS_VERSION_BUILD=${DEVICE_SETTINGS_VER_BUILD} \
  -DRDK_HALIF_DEVICE_SETTINGS_VERSION_ENGINEERING=${DEVICE_SETTINGS_VER_ENG} \
  -DKERNEL_ARPI_VERSION_MAJOR=5 \
  -I${STAGING_DIR_TARGET}${includedir}/rdk/halif/ds-hal/ \
  -Wno-unused-parameter \
  "

# The source's build file turns a requested card0 into card1, which is right
# for the Pi and wrong here. (Done with sed, not in the patch: the file has
# DOS line ends, which a patch does not carry well.)
do_configure:prepend() {
    sed -i '/elseif(DRI_CARD STREQUAL "\/dev\/dri\/card0")/,+2d' ${S}/CMakeLists.txt
}

do_install:append() {
    install -d ${D}${bindir}
    install -m 0644 ${S}/platform.cfg ${D}${bindir}
    install -d ${D}${base_libdir}/rdk
    install -d ${D}${base_libdir}/systemd/system
    install -d ${D}/opt/persistent/ds
    install -m 0755 ${S}/hostData ${D}/opt/persistent/ds/
    # Turns the display on and off with the power state, through Westeros'
    # backend (westeros-gl-console). The names are the Pi's, as its code asks.
    install -m 0755 ${S}/scripts/rpiDisplayEnable.sh ${D}/lib/rdk/rpiDisplayEnable.sh
    install -m 0644 ${S}/systemd/rpiDisplay.service ${D}/lib/systemd/system/rpiDisplay.service
    ln -sr ${D}${libdir}/libds-hal.so.0.0.0 ${D}${libdir}/libdshal.so
}

SYSTEMD_SERVICE:${PN} += "rpiDisplay.service"

FILES:${PN} += "/opt/www/*.html /opt/persistent/ds/ /opt/persistent/ds/* /lib/rdk/* /lib/systemd/system/* ${libdir}/*.so"
FILES_SOLIBSDEV = ""
INSANE_SKIP:${PN} += "dev-so"
