# Westeros on the VM's DRM device with Mesa: what meta-oss-vendor-raspberrypi
# does for the Pi with its Mesa driver, without what is the Pi's (its own
# display card, its resolution module, the Broadcom libraries).

# The release the Pi's vendor layer names.
SRCREV_westeros = "d87a12e80e3b8a5e1c17d8b558db6e29585e3e1b"

CXXFLAGS:append = " -DWESTEROS_PLATFORM_DRM -DUSE_MESA"

# libwayland-egl is a package of its own in RDK-E's layers.
DEPENDS:append = " wayland-default-egl virtual/egl"
RDEPENDS:${PN}:append = " wayland-default-egl"

do_configure:prepend () {
    sed -i -e 's/-lwesteros_simplebuffer_client/-lwesteros_compositor -lwesteros_simplebuffer_client/g' ${S}/Makefile.am
}

do_compile:prepend () {
    export WESTEROS_COMPOSITOR_EXTRA_LIBS="-lEGL -lGLESv2"
}
