# 64-bit programs: RDK-E's middleware is written and tested for 32-bit ARM,
# and prints sizes, 64-bit numbers and times with formats that fit there only
# ("%d" for a size_t, "%lld" for an int64_t). Its recipes make such warnings
# errors, so on a 64-bit machine they stop the build. The warnings stay; they
# are not errors here. RDK's own virtual-device build does the same for its
# power manager plug-in (meta-rdk-video, entservices-powermanager.bb,
# vdevice_x86-64-mw).
#
# What is printed with a wrong format can be printed wrongly. No value that
# is computed with is changed by this.
CFLAGS:append:aarch64 = " -Wno-error=format -Wno-error=format-truncation"
CXXFLAGS:append:aarch64 = " -Wno-error=format -Wno-error=format-truncation"
