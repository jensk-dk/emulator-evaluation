# RDK-E's layers take libwayland-egl out of the wayland package
# (meta-rdk-oss-reference, wayland_%.bbappend): a SoC vendor's graphics
# libraries bring their own. For Mesa the plain one serves, which RDK-E has
# as a package of its own, as the Pi's vendor layer installs it.
DEPENDS:append:tvemu = " wayland-default-egl"
RDEPENDS:${PN}:append:tvemu = " wayland-default-egl"
RDEPENDS:${PN}-examples:append:tvemu = " wayland-default-egl"
