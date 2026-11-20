# As meta-oss-vendor-raspberrypi has it: libwayland-egl is a package of its
# own in RDK-E's layers (see recipes-graphics/wayland/weston_%.bbappend), and
# sound goes through ALSA.
DEPENDS:append:tvemu = " wayland-default-egl"
RDEPENDS:${PN}:append:tvemu = " wayland-default-egl"
PACKAGECONFIG:append:tvemu = " ${@bb.utils.filter('DISTRO_FEATURES', 'alsa', d)}"

# 64-bit programs: a patch of RDK-E's common layer gives a C++ test the
# compiler option -mfloat-abi=hard, which only a 32-bit ARM compiler knows.
SRC_URI:remove:aarch64 = "file://0001-gst-plugins-base-stubs-soft.h-not-existing-compilati.patch"

# Two plug-ins of the middleware name the package with GStreamer's application
# library as what they are built against. In RDK-E's layered build a vendor
# layer's package feed has it under that name; built from source, the recipe
# has to say that it provides it.
PROVIDES:append:tvemu = " gstreamer1.0-plugins-base-app"
