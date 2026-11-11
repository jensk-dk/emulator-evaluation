#!/bin/sh
# Builds emugfx: generates the Wayland protocol code and the SPIR-V shaders,
# then compiles. Used by target/Dockerfile.
#   build-emugfx.sh SOURCE_DIR OUTPUT_FILE
set -eu
src=$1 out=$2
work=$(mktemp -d)
protocols=$(pkg-config --variable=pkgdatadir wayland-protocols)
for xml in stable/xdg-shell/xdg-shell.xml stable/presentation-time/presentation-time.xml; do
  name=$(basename "$xml" .xml)
  wayland-scanner client-header "$protocols/$xml" "$work/$name-client-protocol.h"
  wayland-scanner private-code "$protocols/$xml" "$work/$name-protocol.c"
done
: > "$work/shaders.h"
for shader in background.vert background.frag quad.vert quad.frag; do
  name=$(echo "$shader" | tr . _)_spv
  glslangValidator --quiet -V --vn "$name" -o "$work/$name.h" "$src/shaders/$shader"
  cat "$work/$name.h" >> "$work/shaders.h"
done
gcc -O2 -Wall -Wextra -I"$work" -o "$out" "$src/emugfx.c" "$work"/*-protocol.c \
  $(pkg-config --cflags --libs wayland-client wayland-egl egl glesv2 vulkan) -lm
rm -rf "$work"
