#!/bin/sh
# Builds what the launcher's display window and remote control input need in
# the target: emuscreen (serves the display in container mode), emukeys (shows
# the keys that arrive) and emu-remote.so (the compositor's remote control
# keyboard). Generates the Wayland protocol code first. Used by
# target/Dockerfile.
#   build-display-tools.sh SOURCE_DIR OUTPUT_DIR
set -eu
src=$1 out=$2
work=$(mktemp -d)
generate() {
  wayland-scanner client-header "$1" "$work/$2-client-protocol.h"
  wayland-scanner private-code "$1" "$work/$2-protocol.c"
}
generate "$(pkg-config --variable=pkgdatadir wayland-protocols)/stable/xdg-shell/xdg-shell.xml" xdg-shell
generate "$(pkg-config --variable=pkgdatadir libweston-14-protocols)/weston-output-capture.xml" weston-output-capture
mkdir -p "$out/lib"
gcc -O2 -Wall -Wextra -I"$work" -o "$out/emuscreen" "$src/emuscreen.c" "$work/weston-output-capture-protocol.c" \
  $(pkg-config --cflags --libs wayland-client)
gcc -O2 -Wall -Wextra -I"$work" -o "$out/emukeys" "$src/emukeys.c" "$work/xdg-shell-protocol.c" \
  $(pkg-config --cflags --libs wayland-client xkbcommon)
# A module of the compositor: it is loaded into Weston and uses its library.
gcc -O2 -Wall -Wextra -shared -fPIC -o "$out/lib/emu-remote.so" "$src/emu_remote.c" \
  $(pkg-config --cflags --libs libweston-14 xkbcommon)
rm -rf "$work"
