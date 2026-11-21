# openembedded-core's compiler protects branches unless told otherwise (it is
# configured with --enable-standard-branch-protection, and the tune adds
# -mbranch-protection=standard), which marks a library as safe for branch
# target identification (BTI). The JavaScript interpreter in WebKit is
# assembly that the marking does not hold for: it has no landing instructions
# at the places it jumps to. On a CPU with BTI (an Apple CPU, which a
# host-native VM gives the target) the kernel then ends the web process with
# "undefined instruction" at its first script. A Raspberry Pi 4's CPU has no
# BTI, and does not show it. Taking the tune's option away is not enough,
# since the compiler's own default is the same: WebKit is built with none.
TUNE_CCARGS:remove:tvemu = "-mbranch-protection=standard"
TUNE_CCARGS:append:tvemu = " -mbranch-protection=none"
