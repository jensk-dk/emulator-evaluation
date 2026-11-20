SUMMARY = "Westeros' device backend for DRM/KMS (westeros-gl), for the VM's virtio-gpu"
DESCRIPTION = "The first piece of a vendor layer for tvemu-arm64-rdke. The recipe is the one of \
meta-vendor-raspberrypi-dev without what is the Raspberry Pi's: its limit to machines with the Pi's GPU, its \
resolution patch, and its compiler switches for that GPU."

require recipes-graphics/westeros/westeros.inc

LICENSE = "Apache-2.0"
LICENSE_LOCATION = "${S}/LICENSE"
LIC_FILES_CHKSUM = "file://${LICENSE_LOCATION};md5=7df5a8706277b586ca000838046993d1"

# The release the Pi's vendor layer names (vendor_pkg_versions.inc).
SRC_URI = "git://github.com/rdkcentral/westeros-gl-drm;protocol=https;nobranch=1 \
           file://0001-graphics-frame-buffer-depth.patch \
           "
SRCREV = "762fecb6e406d00a05200a0a6998a11e703e1b4b"
PV = "2.1.4"

S = "${WORKDIR}/git"

COMPATIBLE_MACHINE = "tvemu"

DEPENDS = "wayland virtual/egl glib-2.0 libdrm"

PROVIDES = " \
    virtual/westeros-soc \
    virtual/vendor-westeros-soc \
    virtual/vendor-westeros-drm \
    westeros-soc \
    "
RPROVIDES:${PN} = " \
    virtual/westeros-soc \
    virtual/vendor-westeros-soc \
    westeros-soc \
    "

CFLAGS:append = " -I${STAGING_INCDIR}/libdrm"
# virtio-gpu's one plane takes opaque buffers only (see the patch).
CFLAGS:append = " -DWST_FB_DEPTH=24"

SECURITY_CFLAGS:remove = "-fpie"
SECURITY_CFLAGS:remove = "-pie"

DEBIAN_NOAUTONAME:${PN} = "1"
DEBIAN_NOAUTONAME:${PN}-dbg = "1"
DEBIAN_NOAUTONAME:${PN}-dev = "1"
DEBIAN_NOAUTONAME:${PN}-staticdev = "1"

inherit autotools pkgconfig

# The backend is loaded by name (libwesteros_gl.so), not by its versioned name.
FILES_SOLIBSDEV = ""
FILES:${PN} += "${libdir}/*.so"
INSANE_SKIP:${PN} += "dev-so"
