#!/bin/bash
# Asks Yocto whether RDK-E's middleware resolves for the machine
# tvemu-arm64-rdke: which recipes and which things of a vendor layer are
# missing. Nothing is built.
#
#   rdke/probe-middleware.sh [64|32] [BITBAKE TARGET ...]
#
# It fetches the middleware layers that middleware-manifest-rdke names
# (develop, 2026-11-20; a few MB, to build/rdke-check/middleware) and runs
# bitbake's dry run in the container of check-parse.sh. The default target is
# the middleware's package group.
set -eu
. "$(dirname -- "$0")/lib.sh"
userland=${1:-64}
[ $# -gt 0 ] && shift
prefix=$([ "$userland" = 32 ] && echo lib32- || echo "")
targets=${*:-${prefix}packagegroup-middleware-layer}
fetch_middleware

cat > "$work/probe-in-container.sh" <<'EOT'
#!/bin/bash
userland=$1; shift
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
cd /home/builder && rm -rf probe
. /work/rdk/configure.sh probe "$userland" middleware
[ -f /work/rdk/probe-extra.conf ] && cat /work/rdk/probe-extra.conf >> conf/local.conf
bitbake -k -n "$@" > probe.txt 2>&1
status=$?
# All of what bitbake said, for reading afterwards (build/rdke-check/probe).
cp probe.txt /out/probe-$userland.txt
grep -E "^ERROR|Nothing R?PROVIDES|was skipped|Missing or unbuildable|Tasks Summary|Parsing of|multiple providers|^NOTE: Runtime target" probe.txt | cut -c1-400 | sort | uniq -c | sort -rn | head -${PROBE_LINES:-80}
# With PROBE_HEAD=N: the first N lines bitbake said, when it failed.
[ "$status" = 0 ] || grep -v "^WARNING\|^Loading\|^Parsing recipes:\|^$" probe.txt | head -${PROBE_HEAD:-0}
echo "bitbake's status: $status"
EOT
chmod +x "$work/probe-in-container.sh"
mkdir -p "$work/probe"
"$runtime" run --rm -v "$work/probe:/out" -e PROBE_LINES="${PROBE_LINES:-80}" -e PROBE_HEAD="${PROBE_HEAD:-0}" -v "$work:/work/rdk:ro" \
  -v "$here/meta-tvemu-rdke:/work/meta-tvemu-rdke:ro" \
  tvemu-rdke-check /work/rdk/probe-in-container.sh "$userland" $targets
