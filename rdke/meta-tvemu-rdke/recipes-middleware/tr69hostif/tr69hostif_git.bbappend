require recipes-middleware/include/tvemu-64bit-formats.inc

# 64-bit programs: one place does not compile at all, and would be wrong if
# it did (see the patch).
FILESEXTRAPATHS:prepend:tvemu := "${THISDIR}/files:"
SRC_URI:append:tvemu = " file://0001-yajl-buffer-length-is-a-size_t.patch"

# It also casts small numbers to pointers and back, as keys of hash tables.
# That works with pointers of either size, and is an error under its own
# -Werror where the two sizes differ.
CFLAGS:append:aarch64 = " -Wno-error=int-to-pointer-cast -Wno-error=pointer-to-int-cast"
CXXFLAGS:append:aarch64 = " -Wno-error=int-to-pointer-cast -Wno-error=pointer-to-int-cast -fpermissive"
