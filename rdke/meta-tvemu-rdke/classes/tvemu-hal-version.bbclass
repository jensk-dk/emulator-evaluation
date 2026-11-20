# hal-version.bbclass - Set version variables from HAL headers

# From meta-product-raspberrypi (hal-version.bbclass). That one finds the
# versions by a path that holds in RDK's own checkout only; here the machine
# has included them already (conf/include/rdk-headers-versions.inc).
include conf/include/rdk-headers-versions.inc

python __anonymous () {
    import re

    def parse_hal_version(d, pkg, prefix, enable_feature_below=None):
        """
        Extracts major, minor, build version from the given header package version
        and sets <prefix>_VER_MAJOR, _MINOR, _BUILD, _ENG variables.
        Optionally appends 'rdk-iarmmgrs-hal-unified-v1.0.1' to DISTRO_FEATURES if version <= enable_feature_below.
        """
        hal_ver = d.getVar(f'PV:pn-{pkg}')
        bb.note(f"DEBUG: {pkg} version = {hal_ver}")

        if enable_feature_below and hal_ver:
            cmp_result = bb.utils.vercmp_string(hal_ver, enable_feature_below)
            if cmp_result <= 0:
                features = d.getVar('DISTRO_FEATURES') or ""
                if "rdk-iarmmgrs-hal-unified-v1.0.1" not in features.split():
                    d.setVar('DISTRO_FEATURES', features + " rdk-iarmmgrs-hal-unified-v1.0.1")
                    bb.note(f"[hal-version.bbclass] Added 'rdk-iarmmgrs-hal-unified-v1.0.1' to DISTRO_FEATURES because {pkg} <= {enable_feature_below}")
                else:
                        bb.note(f"[hal-version.bbclass] 'rdk-iarmmgrs-hal-unified-v1.0.1' already present in DISTRO_FEATURES")

        if hal_ver:
            match = re.match(r"(\d+)\.(\d+)\.(\d+)", hal_ver)
            if match:
                major, minor, build = match.groups()
                d.setVar(f"{prefix}_VER_MAJOR", major)
                d.setVar(f"{prefix}_VER_MINOR", minor)
                d.setVar(f"{prefix}_VER_BUILD", build)
                d.setVar(f"{prefix}_VER_ENG", "0")
                bb.note(f"Set {prefix}_VER_MAJOR={major}, _MINOR={minor}, _BUILD={build}")
            else:
                bb.warn(f"[hal-version.bbclass] Could not parse version from: {hal_ver}")
        else:
            bb.warn(f"[hal-version.bbclass] {pkg} revision not found!")

    # Devicesettings HAL
    parse_hal_version(d, "devicesettings-hal-headers", "DEVICE_SETTINGS")

    # IARMMgrs HAL (feature rdk-iarmmgrs-hal-unified-v1.0.1 enabled if version <= 1.0.1)
    parse_hal_version(d, "iarmmgrs-hal-headers", "IARMMGRS", enable_feature_below="1.0.1")

    # TVSettings HAL
    parse_hal_version(d, "tvsettings-hal-headers", "TVSETTINGS")

    #RDK Gstreamer Utils
    parse_hal_version(d, "rdk-gstreamer-utils-headers", "RDK_GSTREAMER")

    # Set default for RDK_GSTREAMER if not found/parsed; check if RDK_GSTREAMER_VER_MAJOR was set by parse_hal_version
    # Workaround to fix a build error in HALIF v2.0.2: PV was added in rdk-gstreamer-utils-headers.bb instead of rdk-headers-versions.inc
    # Ref: https://github.com/rdkcentral/meta-rdk-halif-headers/blob/2.0.2/recipes-rdk-headers/rdk-gstreamer-utils/rdk-gstreamer-utils-headers.bb#L7
    if not d.getVar('RDK_GSTREAMER_VER_MAJOR'):
        bb.warn("[hal-version.bbclass] RDK Gstreamer Utils version not found, setting default to 1.0.0.0")
        d.setVar("RDK_GSTREAMER_VER_MAJOR", "1")
        d.setVar("RDK_GSTREAMER_VER_MINOR", "0")
        d.setVar("RDK_GSTREAMER_VER_BUILD", "0")
        d.setVar("RDK_GSTREAMER_VER_ENG", "0")
}
