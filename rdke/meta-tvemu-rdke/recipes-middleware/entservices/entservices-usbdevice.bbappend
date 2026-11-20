# 64-bit programs: the plug-ins' logging prints 64-bit numbers and sizes with
# formats that fit them on 32-bit ARM only, an error under -Werror=format. As
# for entservices-opencdmi, and as RDK's own virtual-device build does.
CXXFLAGS:append:aarch64 = " -Wno-error=format"

require recipes-middleware/include/tvemu-64bit-formats.inc
