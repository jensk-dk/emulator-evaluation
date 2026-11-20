SUMMARY = "The minimal image with Thunder, the framework of RDK-E's middleware, and its core services"
DESCRIPTION = "Thunder (wpeframework) with its client libraries and the services that need nothing of a \
vendor layer: the message buses, the logger, telemetry and remote feature control. Built with RDK-E's \
middleware layers (rdke/build.sh --middleware). No plug-in that talks to hardware, and no compositor."

require recipes-core/images/core-image-minimal.bb

IMAGE_INSTALL:append = " \
    wpeframework \
    wpeframework-clientlibraries \
    entservices-apis \
    rbus \
    iarmbus \
    rdk-logger \
    telemetry \
    rfc \
    tvemu-remote \
    "

IMAGE_ROOTFS_EXTRA_SPACE = "65536"
