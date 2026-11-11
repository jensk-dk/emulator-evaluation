#!/bin/sh
# Builds the Flutter workload with the Flutter SDK in /opt/flutter. Used by
# target/Dockerfile.
#   build-flutter-demo.sh SOURCE_DIR OUTPUT_DIR
set -eu
src=$1 out=$2
export PATH=/opt/flutter/bin:$PATH
rm -rf /build/app
mkdir -p /build "$out"
cp -a "$src" /build/app
cd /build/app
# Adds the Linux (GTK) runner around the Dart code; existing files are kept.
flutter create --no-pub --platforms=linux --project-name emu_flutter_demo .
runner=linux/runner/my_application.cc
[ -f "$runner" ] || runner=linux/my_application.cc
# The window has no title bar and fills the display.
sed -i 's/gboolean use_header_bar = TRUE;/gboolean use_header_bar = FALSE;/' "$runner"
sed -i 's/gtk_window_set_default_size(window, 1280, 720);/gtk_window_set_default_size(window, 1280, 720);\n  gtk_window_set_decorated(window, FALSE);\n  gtk_window_fullscreen(window);/' "$runner"
grep -q 'use_header_bar = FALSE' "$runner"
grep -q 'gtk_window_fullscreen(window)' "$runner"
flutter build linux --release
cp -a build/linux/*/release/bundle/. "$out"/
flutter --version --machine > "$out/flutter-version.json"
