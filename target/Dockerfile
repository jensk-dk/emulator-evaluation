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
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY src/ /src/
RUN mkdir -p /out \
    && gcc -O2 -Wall -Wextra -pthread -o /out/emubench /src/emubench.c -lm

# ----------------------------------------------------------------- os ---
# Target OS userland shared by both execution modes.
FROM base AS os
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash busybox e2fsprogs iproute2 kmod procps python3 util-linux \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------- target ---
# Container-mode image.
FROM os AS target
COPY rootfs/ /
COPY --from=tools /out/emubench /usr/local/bin/emubench
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
    cat /tmp/initramfs-modules >> /etc/initramfs-tools/modules; \
    apt-get install -y --no-install-recommends "$KERNEL_PACKAGE"; \
    rm -rf /var/lib/apt/lists/* /tmp/initramfs-modules; \
    ls -l /boot

# ------------------------------------------------------------- vmroot ---
# VM-mode root filesystem: the same files as the container image, plus kernel.
FROM vmos AS vmroot
COPY rootfs/ /
COPY --from=tools /out/emubench /usr/local/bin/emubench
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
