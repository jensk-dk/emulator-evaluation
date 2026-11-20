# The vendor layer's settings: meta-vendor-raspberrypi-dev's vendor.inc
# without what is about the Pi's kernel. The repository locations it requires
# (conf/distro/include/repo-details.inc) are given here, since that file is
# in the Pi's vendor layer.

CMF_GIT_ROOT ?= "git://code.rdkcentral.com/r"
CMF_GIT_PROTOCOL ?= "https"
CMF_RDK_COMPONENTS_ROOT_GIT ?= "${CMF_GIT_ROOT}/rdk/components"
CMF_GIT_BRANCH ?= "rdk-next"
CMF_GIT_MASTER_BRANCH ?= "master"
CMF_GIT_SRC_URI_SUFFIX = "protocol=${CMF_GIT_PROTOCOL};nobranch=1"

CMF_GITHUB_ROOT ?= "git://github.com/rdkcentral"
CMF_GITHUB_MAIN_BRANCH ?= "main"
CMF_GITHUB_MASTER_BRANCH ?= "master"
CMF_GITHUB_STABLE2_BRANCH ?= "topic/rdke_mvp"

RDKE_GITHUB_BRANCH ?= "develop"
RDK_GENERIC_ROOT_GIT ?= "git://${RDK_GIT}/rdk/components/generic"

PROJECT_BRANCH ?= "${RDKE_GITHUB_BRANCH}"

# Not taken from the Pi yet: rdke-vendor-bbmask.inc (recipes of the common
# layers that the Pi's vendor layer masks) and vendor_pkg_versions.inc (the
# versions and the package architecture of everything the vendor layer
# delivers). Both belong to the vendor layer's recipes, which this layer does
# not have yet.

DISTRO_FEATURES:append = " VENDOR"
DISTRO_FEATURES:append = " enable_esdk"

LAYER_EXTENSION = "-vendor"

VENDOR_LAYER_EXTENSION = "${MACHINE}${LAYER_EXTENSION}"
PACKAGE_EXTRA_ARCHS:append = " ${VENDOR_LAYER_EXTENSION}"

LICENSE_FLAGS_ACCEPTED += "commercial_gst-fluendo-mpegdemux \
                            commercial_${MLPREFIX}gst-ffmpeg \
                            ${@bb.utils.contains('DISTRO_FEATURES', 'gstreamer1_18','commercial_${MLPREFIX}ffmpeg','commercial_${MLPREFIX}libav',d)} \
                            commercial_libomxil \
                            commercial_gst-openmax \
                            commercial_mpg123 \
                            commercial_${MLPREFIX}x264 \
                            commercial_gstreamer1.0-omx \
                            commercial_${MLPREFIX}gstreamer1.0-libav"

# Marks what is to move into the OSS layer, as on the Pi.
OVERRIDES .= ":rdkv-oss"

# Not taken from the Pi: KERNEL_ARPI_MAJOR_VERSION (its Android kernel).
