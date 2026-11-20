# 64-bit programs: the device settings manager gives the hardware abstraction
# a callback that takes the display's handle as an intptr_t, where the
# interface's header (dsDisplayEventCallback_t) says int. On 32-bit ARM the
# two are the same; on 64-bit the compiler refuses the conversion. It is let
# through here. The handle then arrives cut to 32 bits in that callback: see
# rdke/README.md for what that means and what is not yet looked at.
# (The recipe compiles its C++ sources with CFLAGS.)
CFLAGS:append:aarch64 = " -fpermissive"
CXXFLAGS:append:aarch64 = " -fpermissive"
