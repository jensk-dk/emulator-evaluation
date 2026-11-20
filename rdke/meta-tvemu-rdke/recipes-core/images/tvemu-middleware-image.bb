SUMMARY = "RDK-E's middleware on the virtual machine: its whole package group, with this layer's vendor components"
DESCRIPTION = "What RDK-E's middleware-test-image is for a device: packagegroup-middleware-layer, here with \
packagegroup-hal-tvemu as the vendor side, Westeros with its backend for the VM's display, and the emulator's \
remote control. Built with rdke/build.sh --middleware. No application layer: no browser and no user interface."

require recipes-core/images/core-image-minimal.bb

IMAGE_INSTALL:append = " \
    packagegroup-middleware-layer \
    packagegroup-hal-tvemu \
    westeros \
    westeros-soc-drm \
    libegl-mesa libgles2-mesa libgbm mesa-megadriver \
    tvemu-remote \
    tvemu-device \
    "

IMAGE_ROOTFS_EXTRA_SPACE = "262144"
