# 64-bit programs: rtRemote casts a pointer to a 32-bit number
# (src/rtRemoteValueWriter.cpp), which the compiler refuses where a pointer
# has 64 bits. It is let through; the value it writes is then the pointer's
# lower half, as it would be the whole pointer on 32-bit ARM.
CXXFLAGS:append:aarch64 = " -fpermissive"
