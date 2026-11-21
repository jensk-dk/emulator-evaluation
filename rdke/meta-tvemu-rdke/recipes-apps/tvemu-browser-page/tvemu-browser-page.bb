SUMMARY = "A page for trying the browser on the virtual machine"
DESCRIPTION = "One HTML page, in the root file system: it shows the size of its window, the last key it \
was given and a count of the frames drawn, and puts the last key in its address, where the browser's \
Thunder interface can read it. Shown with: tvemu-app-start HtmlApp file:///usr/share/tvemu/page/index.html"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://index.html"
S = "${WORKDIR}"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${datadir}/tvemu/page
    install -m 0644 ${WORKDIR}/index.html ${D}${datadir}/tvemu/page/index.html
}

FILES:${PN} = "${datadir}/tvemu/page"
