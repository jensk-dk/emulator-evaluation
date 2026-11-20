# As meta-oss-vendor-raspberrypi has it: the WAV encoder, which RDK's
# text-to-speech path needs.
EXTRA_OEMESON:remove:tvemu = "-Dwavenc=disabled"

# 64-bit programs: as for the base plug-ins, a patch of RDK-E's common layer
# sets a compiler option of 32-bit ARM.
SRC_URI:remove:aarch64 = "file://0001-gst-plugins-good-stubs-soft.h-not-existing-error.patch"
