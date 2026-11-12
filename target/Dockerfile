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

# ------------------------------------------------------------ flutter ---
# Builds the Flutter workload with a pinned Flutter SDK. The SDK builds Linux
# applications for x86-64 and ARM64 only; for any other architecture this
# stage records why the image has no Flutter workload.
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
    export PATH=/opt/flutter/bin:$PATH; \
    flutter --disable-analytics; \
    flutter config --no-cli-animations --enable-linux-desktop; \
    flutter precache --linux
COPY src/flutter_demo/ /src/flutter_demo/
COPY src/build-flutter-demo.sh /src/
RUN [ -e /out/flutter/UNAVAILABLE ] || sh /src/build-flutter-demo.sh /src/flutter_demo /out/flutter

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

# ------------------------------------------------------------- target ---
# Container-mode image.
FROM os AS target
COPY --from=rootfs /rootfs/ /
COPY --from=tools /out/emubench /out/emugfx /usr/local/bin/
COPY --from=flutter /out/flutter/ /opt/emu/flutter/
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
COPY --from=tools /out/emubench /out/emugfx /usr/local/bin/
COPY --from=flutter /out/flutter/ /opt/emu/flutter/
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
