# Build definition for the simulated target OS (the Linux client OS image).
#
# One definition produces both execution modes:
#   --target target    container-mode image: target OS userland, services, workloads
#   --target vmimage   VM-mode artifacts: the same userland as an ext4 root
#                      filesystem, plus a Debian kernel and initramfs
#
# Build it through the launcher (./emu build), which supplies the build
# arguments from target/image.json and records the image identity.

ARG BASE_IMAGE=docker.io/library/debian:trixie-slim

# ---------------------------------------------------------------- base ---
FROM ${BASE_IMAGE} AS base
# Pin apt to a dated Debian snapshot so a rebuild resolves the same packages.
# An empty value keeps the base image's live mirrors.
ARG APT_SNAPSHOT=""
RUN set -eu; \
    if [ -n "$APT_SNAPSHOT" ]; then \
      sed -i \
        -e "s|^URIs: http://deb.debian.org/debian-security\$|URIs: http://snapshot.debian.org/archive/debian-security/$APT_SNAPSHOT/|" \
        -e "s|^URIs: http://deb.debian.org/debian\$|URIs: http://snapshot.debian.org/archive/debian/$APT_SNAPSHOT/|" \
        -e "s|^Signed-By:|Check-Valid-Until: no\nSigned-By:|" \
        /etc/apt/sources.list.d/debian.sources; \
      grep -q "snapshot.debian.org/archive/debian/$APT_SNAPSHOT/" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries
ENV DEBIAN_FRONTEND=noninteractive

# -------------------------------------------------------------- tools ---
# Compiles the native workload binaries for the target architecture.
FROM base AS tools
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc libc6-dev pkgconf \
      glslang-tools libegl-dev libgles-dev libvulkan-dev libwayland-dev wayland-protocols \
    && rm -rf /var/lib/apt/lists/*
COPY src/emubench.c src/emugfx.c src/build-emugfx.sh /src/
COPY src/shaders/ /src/shaders/
RUN mkdir -p /out \
    && gcc -O2 -Wall -Wextra -pthread -o /out/emubench /src/emubench.c -lm \
    && sh /src/build-emugfx.sh /src /out/emugfx
# The target's sound device for the audio driver feature (an ALSA plugin).
RUN apt-get update && apt-get install -y --no-install-recommends libasound2-dev \
    && rm -rf /var/lib/apt/lists/*
COPY src/emu_alsa.c /src/
RUN mkdir -p /out/lib \
    && gcc -O2 -Wall -Wextra -shared -fPIC -DPIC -o /out/lib/libasound_module_pcm_emu.so /src/emu_alsa.c \
         -lasound -lpthread
# Loaded into the browser's launcher by the web-bench workload, so that its
# pages may start media with sound.
RUN apt-get update && apt-get install -y --no-install-recommends libwpewebkit-2.0-dev \
    && rm -rf /var/lib/apt/lists/*
COPY src/emu_web_autoplay.c /src/
RUN gcc -O2 -Wall -Wextra -shared -fPIC -o /out/lib/libemu_web_autoplay.so /src/emu_web_autoplay.c \
         $(pkgconf --cflags --libs wpe-webkit-2.0) -ldl
# For the launcher's display window and remote control input: the program
# that serves the display in container mode, the one that shows which keys
# arrive, and the compositor's remote control keyboard (a Weston module).
RUN apt-get update && apt-get install -y --no-install-recommends libweston-14-dev libxkbcommon-dev \
    && rm -rf /var/lib/apt/lists/*
COPY src/emuscreen.c src/emukeys.c src/emu_remote.c src/build-display-tools.sh /src/
RUN sh /src/build-display-tools.sh /src /out

# -------------------------------------------------------------- media ---
# The reference streams of the media-decode workload, and what the STB
# simulator's video on demand application needs: its test title, an MPEG-DASH
# stream, and dash.js, the player library. They are data, the same for every
# target architecture, so this stage runs on the building machine rather than
# under emulation of the target's CPU.
FROM --platform=$BUILDPLATFORM ${BASE_IMAGE} AS media
ARG APT_SNAPSHOT=""
RUN set -eu; \
    if [ -n "$APT_SNAPSHOT" ]; then \
      sed -i \
        -e "s|^URIs: http://deb.debian.org/debian-security\$|URIs: http://snapshot.debian.org/archive/debian-security/$APT_SNAPSHOT/|" \
        -e "s|^URIs: http://deb.debian.org/debian\$|URIs: http://snapshot.debian.org/archive/debian/$APT_SNAPSHOT/|" \
        -e "s|^Signed-By:|Check-Valid-Until: no\nSigned-By:|" \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    apt-get install -y --no-install-recommends ffmpeg python3 ca-certificates; \
    rm -rf /var/lib/apt/lists/*
COPY media/ /src/media/
RUN sh /src/media/build-media.sh /src/media /out/media
RUN sh /src/media/build-abr.sh /out/media/abr
ARG DASHJS_PACKAGE
ARG DASHJS_VERSION
ARG DASHJS_SHA256
RUN python3 /src/media/fetch-dashjs.py "$DASHJS_PACKAGE" "$DASHJS_VERSION" "$DASHJS_SHA256" /out/stb-lib

# ------------------------------------------------------------ flutter ---
# Builds the Flutter workload with a pinned Flutter SDK. The SDK builds Linux
# applications for x86-64 and ARM64 only; for any other architecture this
# stage records why the image has no Flutter workload.
#
# TAR_OPTIONS: the Flutter tool unpacks its downloads with tar, which as root
# gives each file the owner the archive names. One archive (the Gradle
# wrapper) names a user id that a rootless container engine has not mapped
# into the build, where setting it fails and the build with it. The files are
# given to root instead, which is what a build as root leaves them usable by.
FROM base AS flutter
ARG FLUTTER_VERSION
ARG FLUTTER_REVISION
RUN set -eu; \
    mkdir -p /out/flutter; \
    arch=$(dpkg --print-architecture); \
    case "$arch" in \
      amd64|arm64) ;; \
      *) echo "the Flutter SDK ($FLUTTER_VERSION) builds Linux applications for x86-64 and ARM64 only, not for $arch" \
           > /out/flutter/UNAVAILABLE; exit 0 ;; \
    esac; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      ca-certificates clang cmake curl git libgtk-3-dev liblzma-dev libstdc++-14-dev ninja-build pkg-config \
      unzip xz-utils; \
    rm -rf /var/lib/apt/lists/*; \
    git clone --quiet --depth 1 --branch "$FLUTTER_VERSION" https://github.com/flutter/flutter.git /opt/flutter; \
    test "$(git -C /opt/flutter rev-parse HEAD)" = "$FLUTTER_REVISION"; \
    export PATH=/opt/flutter/bin:$PATH TAR_OPTIONS=--no-same-owner; \
    flutter --disable-analytics; \
    flutter config --no-cli-animations --enable-linux-desktop; \
    flutter precache --linux
COPY src/flutter_demo/ /src/flutter_demo/
COPY src/build-flutter-demo.sh /src/
RUN [ -e /out/flutter/UNAVAILABLE ] || TAR_OPTIONS=--no-same-owner sh /src/build-flutter-demo.sh /src/flutter_demo /out/flutter

# ------------------------------------------------------------- rootfs ---
# The target's own files. Their modes are set here, from their content, so the
# image is the same whatever host builds it: a build context that comes from a
# Windows host has no executable bit to go by. A file that starts with "#!" is
# a program; everything else is data.
FROM base AS rootfs
COPY rootfs/ /rootfs/
RUN set -eu; \
    find /rootfs -type d -exec chmod 0755 {} +; \
    find /rootfs -type f -exec chmod 0644 {} +; \
    find /rootfs -type f | while IFS= read -r file; do \
      if [ "$(head -c 2 "$file")" = "#!" ]; then chmod 0755 "$file"; fi; \
    done; \
    test -x /rootfs/opt/emu/init

# ----------------------------------------------------------------- os ---
# Target OS userland shared by both execution modes.
FROM base AS os
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash busybox e2fsprogs iproute2 kmod procps python3 util-linux \
    && rm -rf /var/lib/apt/lists/*
# Graphics: a Wayland compositor (Weston) with its seat service, Mesa's
# OpenGL ES and Vulkan drivers (CPU rasterisers and the virtio GPU drivers),
# and GTK, which the Flutter Linux embedder is built on.
RUN apt-get update && apt-get install -y --no-install-recommends \
      weston seatd \
      libegl1 libgles2 libgl1-mesa-dri libvulkan1 mesa-vulkan-drivers \
      libgtk-3-0t64 fonts-dejavu-core \
      mesa-utils-bin vulkan-tools \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /opt/emu/display /usr/local/bin/emu-display
# Media: FFmpeg's decoders with the ffmpeg program and the mpv player, and
# ALSA, the target's audio interface.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg mpv alsa-utils \
    && rm -rf /var/lib/apt/lists/*
# Web: the WPE WebKit browser engine with Cog, its launcher, and the GStreamer
# plugins WebKit plays media with (MP4 demultiplexing, FFmpeg's decoders, ALSA
# output).
RUN apt-get update && apt-get install -y --no-install-recommends \
      cog libwpewebkit-2.0-1 \
      gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-alsa \
    && rm -rf /var/lib/apt/lists/*
# The certificate authorities the browser trusts: the STB simulator's video
# on demand application plays streams from the internet, over HTTPS.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------- target ---
# Container-mode image.
FROM os AS target
COPY --from=rootfs /rootfs/ /
COPY --from=tools /out/emubench /out/emugfx /out/emuscreen /out/emukeys /usr/local/bin/
COPY --from=flutter /out/flutter/ /opt/emu/flutter/
COPY --from=tools /out/lib/ /opt/emu/lib/
COPY --from=media /out/media/ /opt/emu/media/
COPY --from=media /out/stb-lib/ /opt/emu/stb/lib/
ARG IMAGE_NAME=emu-target
ARG IMAGE_VERSION=0.0.0
ARG DEFINITION_SHA256=unknown
ARG BASE_IMAGE
ARG APT_SNAPSHOT=""
RUN /opt/emu/write-identity "$IMAGE_NAME" "$IMAGE_VERSION" "$DEFINITION_SHA256" "$BASE_IMAGE" "$APT_SNAPSHOT"
ENV EMU_MODE=container
ENTRYPOINT ["/opt/emu/init"]
CMD ["prompt"]

# --------------------------------------------------------------- vmos ---
# Adds the target kernel. Kept ahead of the files that change often so the
# kernel install stays cached.
FROM os AS vmos
ARG KERNEL_PACKAGE
COPY vm/initramfs-modules /tmp/initramfs-modules
RUN set -eu; \
    test -n "$KERNEL_PACKAGE"; \
    apt-get update; \
    apt-get install -y --no-install-recommends initramfs-tools zstd; \
    echo 'MODULES=list' > /etc/initramfs-tools/conf.d/emu.conf; \
    # The target never hibernates. Left to itself, the initramfs is told to \
    # resume from the swap device of the host that builds the image, and the \
    # target then waits half a minute at every boot for a device it never has. \
    echo 'RESUME=none' >> /etc/initramfs-tools/conf.d/emu.conf; \
    cat /tmp/initramfs-modules >> /etc/initramfs-tools/modules; \
    apt-get install -y --no-install-recommends "$KERNEL_PACKAGE"; \
    rm -rf /var/lib/apt/lists/* /tmp/initramfs-modules; \
    ls -l /boot

# ------------------------------------------------------------- vmroot ---
# VM-mode root filesystem: the same files as the container image, plus kernel.
FROM vmos AS vmroot
COPY --from=rootfs /rootfs/ /
COPY --from=tools /out/emubench /out/emugfx /out/emuscreen /out/emukeys /usr/local/bin/
COPY --from=flutter /out/flutter/ /opt/emu/flutter/
COPY --from=tools /out/lib/ /opt/emu/lib/
COPY --from=media /out/media/ /opt/emu/media/
COPY --from=media /out/stb-lib/ /opt/emu/stb/lib/
ARG IMAGE_NAME=emu-target
ARG IMAGE_VERSION=0.0.0
ARG DEFINITION_SHA256=unknown
ARG BASE_IMAGE
ARG APT_SNAPSHOT=""
RUN /opt/emu/write-identity "$IMAGE_NAME" "$IMAGE_VERSION" "$DEFINITION_SHA256" "$BASE_IMAGE" "$APT_SNAPSHOT"

# ------------------------------------------------------------- vmpack ---
# Packs the root filesystem into an ext4 image without needing a mount.
FROM vmroot AS vmpack
COPY --from=vmroot / /rootfs/
RUN set -eu; \
    mkdir -p /out; \
    cp /rootfs/boot/vmlinuz-* /out/vmlinuz; \
    cp /rootfs/boot/initrd.img-* /out/initrd.img; \
    cp /rootfs/etc/emu-image.json /out/image.json; \
    ls /rootfs/lib/modules > /out/kernel-release; \
    used_mb=$(du -sm /rootfs | cut -f1); \
    size_mb=$(( used_mb + used_mb / 4 + 192 )); \
    mke2fs -q -t ext4 -L emu-root -m 0 -d /rootfs /out/rootfs.img "${size_mb}M"; \
    ls -l /out

# ------------------------------------------------------------ vmimage ---
FROM scratch AS vmimage
COPY --from=vmpack /out/ /
