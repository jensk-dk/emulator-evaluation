# A provider with nothing in it, as the Raspberry Pi's vendor layer has it
# (meta-vendor-raspberrypi-dev, recipes-noop): a SoC's audio server. Neither the Pi nor the VM has one.
SUMMARY = "No audio server of a SoC"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PROVIDES = "virtual/audio-service virtual/vendor-audio-service"
RPROVIDES:${PN} = "virtual/audio-service virtual/vendor-audio-service"

ALLOW_EMPTY:${PN} = "1"

do_configure[noexec] = "1"
do_compile[noexec] = "1"
do_install[noexec] = "1"

FILES:${PN} = ""
