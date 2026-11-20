SUMMARY = "The minimal image with Westeros, RDK's Wayland compositor, drawing on the VM's display"
DESCRIPTION = "Westeros with its DRM backend on virtio-gpu, Mesa rendering on the target's CPU or on the \
host's GPU, and Westeros' own test client. No other part of RDK-E's middleware."

require recipes-core/images/core-image-minimal.bb

IMAGE_INSTALL:append = " \
    westeros \
    westeros-soc-drm \
    tvemu-westeros-demo \
    tvemu-remote \
    libegl-mesa libgles2-mesa libgbm mesa-megadriver \
    "

# Mesa and LLVM need more room than the minimal image's default.
IMAGE_ROOTFS_EXTRA_SPACE = "65536"
