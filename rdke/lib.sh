# Shared by check-parse.sh and build.sh: where things are, RDK-E's common
# layers at the versions its vendor manifest names, and the container that
# bitbake runs in (bitbake runs on Linux only).
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
work="$here/../build/rdke-check"
layers="$work/layers"
runtime=${EMU_CONTAINER_RUNTIME:-$(command -v docker >/dev/null 2>&1 && echo docker || echo podman)}
mkdir -p "$layers"

# Repository, tag, directory: as in rdke-common-layers.xml and
# rdke-configs-layers.xml of rdke-generic-manifest 1.1.1, and
# vendor-manifest-raspberrypi (develop, 2026-11-20).
fetch() {
  [ -d "$layers/$3" ] || git -c advice.detachedHead=false clone -q --depth 1 -b "$2" \
    "https://github.com/rdkcentral/$1.git" "$layers/$3"
}
fetch poky rdk-4.7.0 poky
fetch meta-openembedded rdk-4.0.0 meta-openembedded
fetch meta-stack-layering-support 5.0.4 meta-stack-layering-support
fetch meta-rdk-auxiliary 1.10.1 meta-rdk-auxiliary
fetch rdke-common-config 1.0.26 common
fetch rdke-stb-config 1.0.0 profile
fetch meta-rdk-oss-reference 4.14.1 meta-rdk-oss-reference
fetch meta-rdk-halif-headers 5.0.0_hotfix meta-rdk-halif-headers
fetch meta-image-support-rdke 1.0.0 meta-image-support-rdke
# For its local.conf template only; the Pi's recipes are not in the build.
fetch meta-vendor-raspberrypi-dev develop meta-vendor-raspberrypi-dev

# Local changes to what was fetched. Each is needed for a build, not for the
# parse, and is said in README.md.
#
# 1. pseudo, Yocto's fake-root tool: RDK's poky has 1.9.0, which loses track
#    of a directory in the first packaging step of a build in this container
#    ("got *at() syscall for unknown directory"). openembedded-core's own
#    kirkstone branch has 1.9.3, which does not.
if ! grep -q 43cbd8fb4914328094ccdb4bb827d74b1bac2046 "$layers/poky/meta/recipes-devtools/pseudo/pseudo_git.bb"; then
  [ -d "$work/oe-core" ] || git -c advice.detachedHead=false clone -q --depth 1 -b kirkstone --filter=blob:none \
    --sparse https://github.com/openembedded/openembedded-core.git "$work/oe-core"
  git -C "$work/oe-core" sparse-checkout set meta/recipes-devtools/pseudo >/dev/null
  rm -rf "$layers/poky/meta/recipes-devtools/pseudo"
  cp -R "$work/oe-core/meta/recipes-devtools/pseudo" "$layers/poky/meta/recipes-devtools/pseudo"
fi

cat > "$work/Dockerfile" <<'EOT'
FROM ubuntu:22.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    gawk wget git diffstat unzip texinfo gcc g++ make build-essential chrpath socat cpio python3 python3-pip \
    python3-pexpect xz-utils debianutils iputils-ping python3-git python3-jinja2 python3-subunit zstd lz4 file \
    locales ca-certificates && locale-gen en_US.UTF-8 && useradd -m builder
USER builder
WORKDIR /home/builder
EOT
"$runtime" build -q -t tvemu-rdke-check "$work" >/dev/null

# The build configuration, written by a script in the container: the Pi's
# local.conf template, and the Pi's layers and their order with this layer in
# place of the Pi's product, vendor and board support layers.
cat > "$work/configure.sh" <<'EOT'
L=/work/rdk/layers
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
source $L/poky/oe-init-build-env "$1" >/dev/null
sed -e "s/##MACHINE##/tvemu-arm64-rdke/" -e "s/##DISTRO_CODENAME##/kirkstone/g" \
    $L/meta-vendor-raspberrypi-dev/conf/template/local.conf.sample > conf/local.conf
cat >> conf/local.conf <<EOC
RDK_TOOLS_PACKAGES = ""
LAYER_SRC_MODE = "0"
MULTICONFIG = ""
INHERIT:remove = "buildhistory"
TVEMU_USERLAND = "$2"
EOC
cat > conf/bblayers.conf <<EOC
LCONF_VERSION = "6"
BBPATH = "\${TOPDIR}"
BBFILES ?= ""
RDKROOT = "/work/rdk"
BBLAYERS = " \
  $L/meta-image-support-rdke /work/meta-tvemu-rdke $L/meta-rdk-oss-reference $L/profile $L/common \
  $L/meta-rdk-halif-headers $L/poky/meta $L/meta-openembedded/meta-oe $L/meta-openembedded/meta-python \
  $L/meta-openembedded/meta-multimedia $L/meta-openembedded/meta-networking \
  $L/meta-stack-layering-support $L/meta-rdk-auxiliary \
"
EOC
EOT
