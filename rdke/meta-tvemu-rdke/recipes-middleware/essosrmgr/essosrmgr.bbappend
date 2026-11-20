# Essos' resource manager is built twice from one source: its library by this
# recipe of RDK-E's common layer, and its service by the middleware's recipe
# "ermgr". Both install the service's systemd unit, and a recipe that needs
# both finds the file twice and stops. In RDK-E's layered build the two are
# never in one build. With the middleware in the build, the unit is the
# middleware's.
do_install:append:tvemu() {
    if [ "${LAYER_NAME}" = "MIDDLEWARE" ]; then
        rm -f ${D}${systemd_unitdir}/system/ermgr.service
        rmdir -p --ignore-fail-on-non-empty ${D}${systemd_unitdir}/system || true
    fi
}
SYSTEMD_SERVICE:${PN}:tvemu = "${@'' if d.getVar('LAYER_NAME') == 'MIDDLEWARE' else 'ermgr.service'}"
