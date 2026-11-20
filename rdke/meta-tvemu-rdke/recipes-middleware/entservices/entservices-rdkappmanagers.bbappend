# 64-bit programs: the plug-ins' logging prints 64-bit numbers and sizes with
# formats that fit them on 32-bit ARM only, an error under -Werror=format. As
# for entservices-opencdmi, and as RDK's own virtual-device build does.
CXXFLAGS:append:aarch64 = " -Wno-error=format"

# 64-bit programs: a static library of the runtime manager (libGateway.a) is
# compiled without -fPIC and linked into a shared library. A 32-bit ARM linker
# lets that pass; the 64-bit one does not ("relocation ... can not be used
# when making a shared object").
EXTRA_OECMAKE:append:aarch64 = " -DCMAKE_POSITION_INDEPENDENT_CODE=ON"
CXXFLAGS:append:aarch64 = " -fPIC"
CFLAGS:append:aarch64 = " -fPIC"

require recipes-middleware/include/tvemu-64bit-formats.inc
