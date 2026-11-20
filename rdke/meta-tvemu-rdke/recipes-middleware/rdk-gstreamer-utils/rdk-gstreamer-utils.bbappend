# The library links against the platform's part, which a vendor layer's
# package feed brings in RDK-E's layered build. Built from source in one
# build, the package has to name it.
RDEPENDS:${PN}:append:tvemu = " rdk-gstreamer-utils-platform"

# Its header is also in the interface headers' package
# (rdk-gstreamer-utils-headers), which the platform's part is built against.
# A recipe that needs both, as Rialto does, then finds the file twice and
# stops. The headers' package is the interface: this one leaves its copy out.
DEPENDS:append:tvemu = " rdk-gstreamer-utils-headers"
do_install:append:tvemu() {
    rm -f ${D}${includedir}/rdk_gstreamer_utils.h
}
