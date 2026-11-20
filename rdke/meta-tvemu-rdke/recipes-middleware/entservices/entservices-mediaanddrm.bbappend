# 64-bit programs: the plug-ins' logging prints sizes (size_t) with "%d" and
# "%i", an error under -Werror=format where size_t is not an int. As for
# entservices-opencdmi, and as RDK's own virtual-device build does.
CXXFLAGS:append:aarch64 = " -Wno-error=format"

require recipes-middleware/include/tvemu-64bit-formats.inc
