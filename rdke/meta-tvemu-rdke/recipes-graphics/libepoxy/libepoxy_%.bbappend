# RDK's patch to libepoxy takes the names of the graphics libraries from the
# build, for the vendor layer to give (a device's own EGL and OpenGL ES
# libraries). Without them libepoxy looks for a library called "EGL_LIB_NAME",
# and the browser's web process ends at its first drawing call. Here they are
# Mesa's.
CFLAGS:append:tvemu = " -DEGL_LIB_NAME=libEGL.so.1 -DGLES2_LIB_NAME=libGLESv2.so.2 \
    -DGLES1_LIB_NAME=libGLESv1_CM.so.1 -DGLX_LIB_NAME=libGL.so.1"
