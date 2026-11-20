#!/bin/bash
# Builds a minimal image for the machine tvemu-arm64-rdke: openembedded-core's
# core-image-minimal on RDK-E's common layers (its base system, its systemd),
# with this machine's kernel. No RDK middleware, and no vendor layer.
#
#   rdke/build.sh [64|32] [BITBAKE TARGET ...]
#
# 64 (the default) builds 64-bit programs, which a host-native VM on a Mac
# needs; 32 is RDK-E's own arrangement (see README.md). The build runs in an
# Ubuntu 22.04 container and keeps its work (downloads, shared state, tmp) in
# the container engine's volume "tvemu-rdke-build", since Yocto needs a Linux
# file system: 30 GB and more, and hours the first time. The kernel and the
# root file system are then copied to build/rdke/arm64, where
# "emu run --mode vm --rootfs rdke" looks for them.
set -eu
. "$(dirname -- "$0")/lib.sh"
userland=${1:-64}
[ $# -gt 0 ] && shift
targets=${*:-core-image-minimal}
out="$here/../build/rdke/arm64"
mkdir -p "$out"

cat > "$work/build-in-container.sh" <<'EOT'
#!/bin/bash
userland=$1; shift
cd /build
. /work/rdk/configure.sh /build/build-$userland "$userland"
cat >> conf/local.conf <<EOC
DL_DIR = "/build/downloads"
SSTATE_DIR = "/build/sstate-cache"
# The work of a recipe is removed when it is built: the volume is small.
INHERIT += "rm_work"
BB_NUMBER_THREADS = "4"
PARALLEL_MAKE = "-j 6"
EOC
[ -f /work/rdk/local-extra.conf ] && cat /work/rdk/local-extra.conf >> conf/local.conf
bitbake "$@" || exit 1
deploy=tmp/deploy/images/tvemu-arm64-rdke
cp -L $deploy/Image /out/Image
image=$(ls -t $deploy/*.ext4 | head -1)
cp -L "$image" /out/rootfs.ext4
echo "copied Image and $(basename "$image") (as rootfs.ext4)"
EOT
chmod +x "$work/build-in-container.sh"

"$runtime" volume create tvemu-rdke-build >/dev/null
"$runtime" run --rm --user root -v tvemu-rdke-build:/build tvemu-rdke-check chown builder:builder /build
"$runtime" run --rm -v "$work:/work/rdk:ro" -v "$here/meta-tvemu-rdke:/work/meta-tvemu-rdke:ro" \
  -v tvemu-rdke-build:/build -v "$out:/out" tvemu-rdke-check /work/rdk/build-in-container.sh "$userland" $targets
