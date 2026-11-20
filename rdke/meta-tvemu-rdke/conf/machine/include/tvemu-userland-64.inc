# 64-bit programs only: no multilib. The targets are then named without the
# Pi's "lib32-" prefix (packagegroup-vendor-layer, vendor-test-image), and the
# Pi's 32-bit middleware and application package feeds do not fit: those
# layers have to be built for this machine.
