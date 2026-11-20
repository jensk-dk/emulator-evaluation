SUMMARY = "The hardware-facing components of tvemu-arm64-rdke"
DESCRIPTION = "What packagegroup-hal-raspberrypi4 is for the Raspberry Pi 4: the vendor layer's \
implementations of RDK-E's hardware abstraction, here for the virtual machine."
LICENSE = "MIT"

PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup

RDEPENDS:${PN} = " \
    sysint-soc \
    devicesettings-hal-tvemu \
    hdmicec-hal-tvemu \
    pwrmgr-hal-tvemu \
    deepsleepmgr-hal-tvemu \
    mfrlibs-hal-tvemu \
    miracast-hal-tvemu \
    displayinfo-soc \
    systemaudioplatform \
    rdk-gstreamer-utils-platform \
    audio-service-tvemu \
    gst-drm-plugins-tvemu \
    secapi2-adapter-tvemu \
    "
