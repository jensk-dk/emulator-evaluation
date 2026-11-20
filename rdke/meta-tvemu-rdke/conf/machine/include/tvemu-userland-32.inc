# The Raspberry Pi's arrangement, from its product.inc: a 32-bit ARMv7
# userland ("lib32") on the 64-bit kernel, so that RDK-E's targets keep their
# names (lib32-packagegroup-vendor-layer) and its 32-bit package feeds fit.
# The VM's CPU must execute 32-bit ARM code: not so under Apple's hypervisor.
require conf/multilib.conf
MULTILIBS = "multilib:lib32"
DEFAULTTUNE:virtclass-multilib-lib32 = "armv7athf-neon-vfpv4"
