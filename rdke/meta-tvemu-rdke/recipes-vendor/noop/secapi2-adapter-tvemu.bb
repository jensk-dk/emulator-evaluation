# A provider with nothing in it, as the Raspberry Pi's vendor layer has it
# (meta-vendor-raspberrypi-dev, recipes-noop): a SoC's adapter for RDK's security API. The VM has no secure element.
SUMMARY = "No adapter for RDK's security API"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PROVIDES = "virtual/secapi2-adapter virtual/vendor-secapi2-adapter"
RPROVIDES:${PN} = "virtual/secapi2-adapter virtual/vendor-secapi2-adapter"

ALLOW_EMPTY:${PN} = "1"

do_configure[noexec] = "1"
do_compile[noexec] = "1"
do_install[noexec] = "1"

FILES:${PN} = ""
