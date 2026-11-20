# The product settings of the machine: meta-product-raspberrypi's product.inc
# with what is about the Raspberry Pi's boot firmware and GPU taken out or
# replaced. Lines that are RDK's are kept in RDK's order, with RDK's comments
# shortened.

TARGET_VENDOR = "-rdk"

# Not taken from the Pi: SDKVERSION (names the Pi's board support package),
# ENABLE_UART, VC4DTBO and RPI_EXTRA_CONFIG (the Pi's boot firmware).

# tmp, not tmp-glibc.
TCLIBCAPPEND = ""

# Needed for RDK's systemd patches to apply (RDKE-12).
MACHINEOVERRIDES .= ":kirkstone"
DISTRO_FEATURES:append = " kirkstone"

# 64-bit or 32-bit programs on the 64-bit kernel. The Pi runs a 32-bit
# userland (multilib "lib32", ARMv7), and its package feeds are built that
# way. A host-native VM cannot follow it everywhere: Apple's CPUs do not
# execute 32-bit ARM code at all, so on a Mac only 64-bit programs run in the
# VM. "64" is therefore the default; "32" is the Pi's arrangement, for hosts
# whose CPU runs 32-bit ARM code under KVM and for the simulated CPU.
TVEMU_USERLAND ?= "64"
require conf/machine/include/tvemu-userland-${TVEMU_USERLAND}.inc

# syslog-ng's packaging needs sysvinit out of the way (RDKE-14).
DISTRO_FEATURES_BACKFILL_CONSIDERED += "sysvinit"
VIRTUAL-RUNTIME_init_manager = "systemd"
VIRTUAL-RUNTIME_initscripts = "systemd-compat-units"

# Middleware layer requirements.
DOBBY_DEVICESETTINGS_FILE = "dobby.generic.json"

# No secure video path.
DISTRO_FEATURES:remove = " rdk_svp"

# No SecAPI: crypto through OpenSSL.
DISTRO_FEATURES:append = " enable_icrypto_openssl"

# RDK-52444, as on the Pi.
SECURITY_CFLAGS:remove = " -fstack-protector -D_FORTIFY_SOURCE=2 -Wformat -Wformat-security -Wno-error=format-security -Wno-error=unused-result"
SECURITY_LDFLAGS:remove = " -fstack-protector"

BUILD_VARIANT ?= "debug"

# No DRM systems: the VM has no provisioned keys.
OPENCDM_DRMS = ""

# The display device. On the Pi it is card1 (card0 is the 3D core); the VM has
# one DRM device, virtio-gpu.
DRI_DEVICE_NAME = "/dev/dri/card0"

DISTRO_FEATURES:remove = " subtec"

# Downloadable application containers. The Pi's firmware compatibility key
# and platform name tell an app store which container builds fit the device;
# no store has builds for this machine, and none for 64-bit programs.
DAC_BUN_PLATNAME_OVERRIDE = "tvemu"

DAC_APP_PATH = "/opt/dac_apps/apps"
DAC_APP_CERT_PATH = "/etc/rdk/certs"
FACTORY_APP_PATH = "/etc/rdk/factoryapps"
APP_PREINSTALL_DIRECTORY = "/opt/media/apps"
# The trailing slash is required: the package manager appends the name to it.
APP_DOWNLOAD_DIRECTORY = "/opt/CDL/"
DEFAULT_APP_STORAGE_PATH = "/opt/persistent/storageManager"

DISTRO_FEATURES:append = " vulkan"
DISTRO_FEATURES:append = " vulkan-devtools"

BROWSER_MEMORYPROFILE = "fhd"

# The OSS package feed of the stack layering, as on the Pi.
DISTRO_FEATURES:append = " STACK_LAYER_OSS_SUPPORT"

CFLAGS:remove:pn-telemetry = "-DENABLE_MTLS"

# Not taken from the Pi: INHERIT += "repo-info", a class of
# meta-product-raspberrypi that writes the repositories' revisions into the
# image's version.txt. This layer is not checked out with "repo".

TEXTTOSPEECH_ENDPOINT ?= "ttsurl"
TEXTTOSPEECH_SECURE_ENDPOINT ?= "ttssecureurl"
TEXTTOSPEECH_LOCAL_ENDPOINT ?= "ttslocalurl"
TEXTTOSPEECH_LANGUAGE ?= "en-US"
TEXTTOSPEECH_VOICE_FOR_EN ?= "carol"
TEXTTOSPEECH_VOICE_FOR_ES ?= "Angelica"
TEXTTOSPEECH_VOICE_FOR_FR ?= "amelie"
TEXTTOSPEECH_VOICE_FOR_GB ?= "en-GB-Standard-N"
TEXTTOSPEECH_VOICE_FOR_DE ?= "de-DE-Standard-G"
TEXTTOSPEECH_VOICE_FOR_IT ?= "it-IT-Standard-E"
TEXTTOSPEECH_SPEECHRATE ?= "medium"
TEXTTOSPEECH_ENDPOINT_TYPE ?= "TTS2"
TEXTTOSPEECH_SATPLUGINCALLSIGN ?= ""
TEXTTOSPEECH_LOCALVOICE_FOR_EN ?= "ava"
TEXTTOSPEECH_LOCALVOICE_FOR_ES ?= "angelica"
TEXTTOSPEECH_LOCALVOICE_FOR_FR ?= "amelie"
