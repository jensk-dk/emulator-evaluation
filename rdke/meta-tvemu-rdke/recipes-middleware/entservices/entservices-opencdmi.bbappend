# 64-bit programs: the plug-in prints a size_t with "%d" (client/CapsParser.cpp),
# which is an error under -Werror=format where size_t is not an int. RDK's own
# virtual-device build relaxes the same warning for its power manager plug-in
# (meta-rdk-video, entservices-powermanager.bb, vdevice_x86-64-mw).
CXXFLAGS:append:tvemu = " -Wno-error=format"

# A plug-in that cannot start must not take Thunder down with it (see the patch).
FILESEXTRAPATHS:prepend:tvemu := "${THISDIR}/files:"
SRC_URI:append:tvemu = " file://0001-ocdm-deinitialize-once.patch"
