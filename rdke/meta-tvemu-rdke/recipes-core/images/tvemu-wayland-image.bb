SUMMARY = "The minimal image with a Wayland compositor that draws on the VM's display"
DESCRIPTION = "A step toward RDK-E's own compositor: Weston on virtio-gpu through DRM/KMS, with Mesa \
rendering on the target's CPU or on the host's GPU, and a client that draws. Nothing in it is RDK's \
middleware."

require recipes-core/images/core-image-minimal.bb

IMAGE_INSTALL:append = " \
    weston \
    weston-examples \
    tvemu-wayland-demo \
    tvemu-remote \
    libegl-mesa libgles2-mesa libgbm mesa-megadriver \
    kmscube \
    "

# Mesa, LLVM and the fonts need more room than the minimal image's default.
IMAGE_ROOTFS_EXTRA_SPACE = "65536"
