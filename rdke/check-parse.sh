#!/bin/bash
# Checks that Yocto parses the machine tvemu-arm64-rdke together with RDK-E's
# common layers, with a 64-bit and with a 32-bit userland. Nothing is built.
#
#   rdke/check-parse.sh
#
# It fetches the layers that RDK-E's vendor manifest names (about 120 MB, to
# build/rdke-check/layers, which is not version controlled) and runs bitbake
# in an Ubuntu 22.04 container, since bitbake runs on Linux only. Needs git
# and the container runtime that the emulator uses (docker or podman).
set -eu
. "$(dirname -- "$0")/lib.sh"

cat > "$work/in-container.sh" <<'EOT'
#!/bin/bash
cd /home/builder && rm -rf build
. /work/rdk/configure.sh build "$1"
failed=0
echo "=== TVEMU_USERLAND = $1: the configuration"
bitbake -e > env.txt 2> env.err || { failed=1; tail -20 env.err; }
grep -E '^(MACHINE|MACHINEOVERRIDES|DEFAULTTUNE|MULTILIBS|PACKAGE_ARCHS|MACHINE_FEATURES|KERNEL_IMAGETYPE|IMAGE_FSTYPES|PREFERRED_PROVIDER_virtual/kernel|PREFERRED_PROVIDER_virtual/egl|DRI_DEVICE_NAME|VENDOR_LAYER_EXTENSION)=' env.txt
echo "=== TVEMU_USERLAND = $1: every recipe"
bitbake -p > parse.txt 2>&1 || failed=1
grep -E "^ERROR|Parsing of .* complete" parse.txt
echo "=== TVEMU_USERLAND = $1: the kernel and Mesa"
bitbake -e virtual/kernel 2>/dev/null | grep -E '^(PN|PV|KMACHINE|COMPATIBLE_MACHINE|SRC_URI)=' || failed=1
bitbake -e mesa 2>/dev/null | grep -E '^(PV|PACKAGECONFIG|GALLIUMDRIVERS)=' || failed=1
exit $failed
EOT
chmod +x "$work/in-container.sh"

status=0
for userland in 64 32; do
  "$runtime" run --rm -v "$work:/work/rdk:ro" -v "$here/meta-tvemu-rdke:/work/meta-tvemu-rdke:ro" \
    tvemu-rdke-check /work/rdk/in-container.sh "$userland" || status=1
done
[ "$status" = 0 ] && echo "PASS: tvemu-arm64-rdke parses with both userlands" || echo "FAIL"
exit $status
