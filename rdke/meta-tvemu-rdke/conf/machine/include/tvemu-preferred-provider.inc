# Which recipe provides each thing the middleware expects of a vendor layer:
# meta-product-raspberrypi's preferred_provider.inc, with the Pi's recipes
# replaced.

# --- kernel: qemuarm64 -----------------------------------------------------
# The Pi builds "android-raspberrypi", an Android common kernel for its SoC.
# The VM uses openembedded-core's kernel for QEMU machines, with the options
# RDK-E needs added by this layer (recipes-kernel/linux).
PREFERRED_PROVIDER_virtual/kernel = "linux-yocto"
PREFERRED_VERSION_linux-yocto ?= "5.15%"

# --- graphics: qemuarm64 ---------------------------------------------------
# On the Pi these depend on "vc4graphics" and fall back to the Broadcom
# "userland" libraries. Here it is Mesa, on virtio-gpu: with the host's GPU
# behind it (virgl) where the emulator maps graphics to the host, and
# rendering on the CPU (llvmpipe) where it does not.
PREFERRED_PROVIDER_virtual/egl = "mesa"
PREFERRED_PROVIDER_virtual/libgles1 = "mesa"
PREFERRED_PROVIDER_virtual/libgles2 = "mesa"
PREFERRED_PROVIDER_virtual/libgles3 = "mesa"
PREFERRED_PROVIDER_virtual/libgl = "mesa"
PREFERRED_PROVIDER_virtual/mesa = "mesa"
PREFERRED_PROVIDER_virtual/libgbm = "mesa"
PACKAGECONFIG:append:pn-mesa = " gallium gallium-llvm virgl"

# --- the compositor's device side: raspberrypi4-64-rdke --------------------
# Westeros on DRM/KMS, as on the Pi. The recipe (westeros-soc-drm) is in the
# Pi's vendor layer and is limited to machines with "vc4graphics"; this
# layer needs its own.
PREFERRED_PROVIDER_virtual/vendor-westeros-drm = "westeros-soc-drm"
PREFERRED_PROVIDER_virtual/vendor-westeros-soc = "westeros-soc-drm"
PREFERRED_PROVIDER_virtual/vendor-westeros-sink = "westeros-sink"

# --- hardware abstraction: to be written -----------------------------------
# The Pi's recipes are named ...-hal-raspberrypi4 and talk to its hardware.
# The names below are the ones this layer is to provide; none exists yet, so
# a build of the vendor layer stops at the first of them.
PREFERRED_PROVIDER_virtual/vendor-devicesettings-hal = "devicesettings-hal-tvemu"
PREFERRED_PROVIDER_virtual/vendor-iarmmgrs-hal = "iarmmgrs-hal-tvemu"
PREFERRED_PROVIDER_virtual/vendor-pwrmgr-hal = "pwrmgr-hal-tvemu"
PREFERRED_PROVIDER_virtual/vendor-deepsleepmgr-hal = "deepsleepmgr-hal-tvemu"
PREFERRED_PROVIDER_virtual/mfrlib = "mfrlibs-hal-tvemu"
PREFERRED_PROVIDER_virtual/vendor-hdmicec-hal = "hdmicec-hal-tvemu"
PREFERRED_PROVIDER_virtual/vendor-rdk-gstreamer-utils-platform = "rdk-gstreamer-utils-platform"
PREFERRED_PROVIDER_virtual/vendor-audio-service = "audio-service-tvemu"
PREFERRED_PROVIDER_virtual/vendor-gst-drm-plugins = "gst-drm-plugins-tvemu"
PREFERRED_PROVIDER_virtual/vendor-secapi2-adapter = "secapi2-adapter-tvemu"
PREFERRED_PROVIDER_virtual/vendor-systemaudioplatform = "systemaudioplatform"
PREFERRED_PROVIDER_virtual/vendor-displayinfo-soc = "displayinfo-soc"
PREFERRED_PROVIDER_virtual/vendor-miracast-soc = "miracast-hal-tvemu"

# --- unchanged from the Pi: RDK's own stand-ins and common recipes ---------
PREFERRED_PROVIDER_virtual/vendor-tvsettings-hal = "tvsettings-hal-noop"
PREFERRED_PROVIDER_virtual/vendor-motiondetector-hal = "motiondetector-hal-noop"
PREFERRED_PROVIDER_virtual/vendor-media-utils = "media-utils"
PREFERRED_PROVIDER_virtual/cobalt-evergreen = "cobalt-evergreen-src"
