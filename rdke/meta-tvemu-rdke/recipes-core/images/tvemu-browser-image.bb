SUMMARY = "RDK-E's middleware on the virtual machine, with RDK's browser and reference user interface"
DESCRIPTION = "tvemu-middleware-image with WPE WebKit, its Thunder plug-in (WebKitBrowser, HtmlApp, \
LightningApp, ResidentApp) and its backend for Westeros. RDK-E's own configuration leaves these out of the \
middleware's package group (the distro feature enable_bolt_apps) and delivers the browser as an application \
package; here they are in the image, as on RDK devices before that. RDK's reference user interface \
starts in the browser at boot (tvemu-refui), and there is a page to try the browser on (tvemu-browser-page)."

require tvemu-middleware-image.bb

IMAGE_INSTALL:append = " \
    wpe-webkit \
    libwpe \
    wpe-backend-rdk \
    wpe-backend-rdk-platform-plugin \
    wpe-webkit-web-inspector-plugin \
    webkitbrowser-plugin \
    tvemu-app-start \
    tvemu-refui \
    tvemu-browser-page \
    "

IMAGE_ROOTFS_EXTRA_SPACE = "393216"
