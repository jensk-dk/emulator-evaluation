# RDK-E on tv-emu: a proposal, in its first step

A trial of running [RDK-E](https://wiki.rdkcentral.com/x/pVNKG), RDK's stack
for IP video devices, in this emulator. It is a finding and a proposal, not
an agreed requirement: nothing in `openspec/specs/` asks for it, the launcher
does not know it, and it is not part of the target image (`target/`), whose
definition it must not change.

**What there is: a machine definition, and a minimal image built from it
that boots host-native to a root shell on a Mac. The image has RDK-E's base
system and none of its middleware: no RDK service runs in it.**

## The machine: `tvemu-arm64-rdke`

RDK-E is built with Yocto (kirkstone) in three layers that are built apart:
vendor, middleware and application. A device is described by a *machine*
definition and a vendor layer that implements the hardware side. RDK-E's
public reference is the Raspberry Pi 4 (`raspberrypi4-64-rdke`).

[meta-tvemu-rdke](meta-tvemu-rdke) is a Yocto layer with a machine for
tv-emu's ARM64 VM. It is a fusion of two definitions, and every block in its
files says which of the two it is from:

| From | Taken |
|---|---|
| `raspberrypi4-64-rdke` (meta-product-raspberrypi, meta-vendor-raspberrypi-dev) | What makes a machine an RDK-E machine: the includes of the common, middleware and application layers, the overrides `client`, `wpe` and `lxcsecure`, the product settings (systemd, no secure video path, crypto through OpenSSL, the application paths), the vendor layer's package architecture, the list of virtual providers the middleware expects, and the kernel options RDK-E needs (binder, dm-verity, EROFS, AppArmor) |
| `qemuarm64` (openembedded-core) | The hardware: QEMU's `virt` board, the `linux-yocto` kernel, the serial and virtio consoles, Mesa as the graphics stack, a bare ext4 root file system with the kernel beside it, as the launcher boots a VM |
| Neither | The devices of tv-emu's VM in the kernel (virtio disk, network, GPU, input, sound), `/dev/dri/card0` as the display device, Mesa with virgl and llvmpipe |

Left out of the Pi's definition: its boot firmware, device trees, SD card
image, Wi-Fi and Bluetooth firmware, the Broadcom graphics libraries, its
Android kernel, and the overrides `rpi` and `raspberrypi4-64`.

The files:

- `conf/machine/tvemu-arm64-rdke.conf`: the machine.
- `conf/machine/include/tvemu-product.inc`, `tvemu-vendor.inc`,
  `tvemu-preferred-provider.inc`: what the Pi has in `product.inc`,
  `vendor.inc` and `preferred_provider.inc`.
- `conf/machine/include/tvemu-userland-64.inc`, `-32.inc`: see below.
- `recipes-kernel/linux/`: the kernel options, added to `linux-yocto`.

## Host-native means 64-bit programs, and RDK-E is built 32-bit

The Raspberry Pi runs a 64-bit kernel with a **32-bit** userland (Yocto's
multilib `lib32`, ARMv7), and RDK-E's package feeds are built that way.

A host-native VM runs the guest's code on the host's CPU. Apple's CPUs do not
execute 32-bit ARM code at all, so on a Mac a host-native ARM64 VM can run
64-bit programs only. The machine therefore has a setting:

- `TVEMU_USERLAND = "64"` (the default): 64-bit programs only, no multilib.
  This is what host-native on a Mac needs. RDK-E does not do this anywhere
  that was found: its helper that names the package architecture
  (`meta-stack-layering-support`, `get_toolchain_arch`) knows the Pi's
  arrangement and 32-bit CPUs, and calls this one `rdk-arm7ve`, which is
  wrong. The Pi's middleware and application feeds do not fit; both layers
  would have to be built for 64-bit, and it is not known that they build.
- `TVEMU_USERLAND = "32"`: the Pi's arrangement. For a host whose CPU runs
  32-bit ARM code under KVM, and for the simulated CPU (`vm-arm64`). The Pi's
  feeds have the right architecture then (`rdk-arm64`).

On an x86-64 host, host-native is an x86-64 VM, and this machine is not that:
there it is the `vm-arm64` mode, on a simulated CPU. An x86-64 machine would
fuse `qemux86-64` with the same RDK-E parts; RDK-E has no public x86 build.

## Building the minimal image

    rdke/build.sh            # 64-bit programs, for a host-native VM
    rdke/build.sh 32         # RDK-E's own arrangement; not built yet

builds openembedded-core's `core-image-minimal` for the machine, on RDK-E's
common layers, in an Ubuntu 22.04 container, and copies the kernel and the
root file system to `build/rdke/arm64`. Built on the macOS host (ARM64, the
container engine with 6 CPUs and 8 GB) on 2026-11-20: 2379 tasks, no error
left. The kernel is 21 MB and the root file system 57 MB. The build's work is
kept in the container engine's volume `tvemu-rdke-build`, 18 GB after the
build, 12 GB of it downloads; `docker volume rm tvemu-rdke-build` removes it.

What is in the image: the `linux-yocto` 5.15 kernel with this layer's
options, glibc and BusyBox, and RDK-E's systemd 230 (from
`meta-rdk-oss-reference`) with RDK's logger. What is not: Thunder, the
entertainment services, Westeros, a browser, or anything else of RDK-E's
middleware and application layers, and no hardware abstraction.

Two things had to be changed to get there, both kept in the scripts:

- **Yocto's fake-root tool.** RDK's fork of poky has pseudo 1.9.0, with which
  the first packaging step failed every time in this container
  (`linux-libc-headers`, "got *at() syscall for unknown directory").
  `rdke/lib.sh` replaces the recipe with the one of openembedded-core's own
  kirkstone branch (1.9.3), in the fetched copy of poky.
- **Yocto's own QEMU.** Every image of a QEMU machine builds QEMU for the
  build host, for `runqemu`. The machine takes that out
  (`EXTRA_IMAGEDEPENDS`): the emulator has its own.

What the image showed when it was started (`./emu run --mode vm --rootfs
rdke`, host-native on the Mac's hypervisor, the guest reporting the Apple
CPU):

- It boots to a root shell on the console in about 2 s, with an automatic
  login, which the Pi's build configuration turns on (`debug-tweaks`).
- systemd is RDK's 230, and the system comes up "degraded": RDK's
  `syslog-ng.service` ends with status 2 and is not started again. Not
  looked into; its configuration is RDK's.
- The kernel options hold as far as they were looked at: `/dev/binder` is
  there, AppArmor is among the active security modules, and virtio-gpu is
  `/dev/dri/card0` with a render node.
- There is no sound device and no network address: the launcher gives an
  RDK-E target no sound card yet, and the minimal image configures no
  network.

## Starting an image

    ./emu run --mode vm --rootfs rdke [--window]

The launcher does not build the image. It looks in `build/rdke/arm64` (or in
the directory that `--option rdke-dir=DIR` names) for

- the kernel, as `Image` (Yocto's name for it; `vmlinuz` is taken too),
- the root file system, as `rootfs.ext4` (or `rootfs.img`): the image's
  `.ext4` file from Yocto's `tmp/deploy/images/tvemu-arm64-rdke/`, copied
  under that name,
- and, only if the image has one, an initial RAM disk as `initrd.img`.

It boots them in an ARM64 VM (`--arch native` on an ARM64 host, `--arch
arm64` on others) with a virtio disk, network and display, and with the
kernel command line `console=ttyAMA0 root=/dev/vda rootfstype=ext4 rw`. The
root file system is not written to: changes are discarded when the VM ends.
The target's console is in the terminal, boot messages included
(`--option verbose-boot=no` turns them off).

What is typed or piped into the launcher goes to the target's console, so
the shell can be used from a script as well:

    (sleep 10; echo 'uname -a'; sleep 2) | ./emu run --mode vm --rootfs rdke --timeout 20

`./emu verify rootfs-option` checks this path with a stand-in, the ARM64
Debian VM image started the same way, and with the image in
`build/rdke/arm64` where a host has built one.

## What is checked

    rdke/check-parse.sh

fetches RDK-E's common layers at the versions its vendor manifest names and
runs Yocto's parser (bitbake) on them with this machine, in a container,
once for each userland. Run on macOS (ARM64) on 2026-11-20: the configuration
and all 2658 recipes parse with 0 errors in both, the kernel is `linux-yocto`
5.15 for `qemuarm64` with this layer's four option files, and Mesa 22.0.3 has
the `virgl` and `swrast` drivers.

That shows that the definition is consistent with RDK-E's common layers.
That it builds and boots is shown by the minimal image above, with the
64-bit userland only.

## What is open

1. **A vendor layer.** The machine names recipes that do not exist: the
   hardware abstraction for device settings, power, deep sleep, HDMI-CEC,
   manufacturer data and others (`...-hal-tvemu`), and Westeros' DRM backend,
   which the Pi's layer limits to its own GPU. A build of the vendor layer
   stops at the first of them. The Pi's `vendor_pkg_versions.inc`, which pins
   the versions of what a vendor layer delivers, is not taken over either.
2. **Building more than the minimal image.** That one fits the container
   engine's disk on the Mac; RDK-E's middleware, with a browser, is on the
   order of 100 GB and hours, and needs another build host or a larger
   engine disk. The 32-bit userland is not built at all.
3. **The kernel options, in full.** Binder, AppArmor and virtio-gpu were
   seen at work in the booted image; dm-verity, EROFS and sound were not
   looked at. `CONFIG_ASHMEM`, which the Pi sets, is left out.
4. **Pi-specific settings in the middleware.** Recipes of the middleware may
   key on `rpi` or `raspberrypi4`; without those overrides such settings do
   not apply here. The middleware layers have not been read for this.
5. **The launcher's side, in part.** `./emu run --mode vm --rootfs rdke`
   boots an image from `build/rdke/arm64` (see below), and that path is
   verified with a stand-in only. How the remote control's keys reach an
   RDK-E target is not done: nothing in RDK-E fetches them from the
   launcher's window. Sound is not connected either.
6. **RDK's own virtual device.** RDK's build scripts mention a "vdevice"
   product layer (build-scripts, pull request 30, June 2026). No public
   repository of it was found on 2026-11-20. If one is published, it may be
   a better base than this fusion.

## Sources

Read on 2026-11-20, all Apache-2.0 or MIT: `vendor-manifest-raspberrypi`
(develop), `meta-product-raspberrypi`, `meta-vendor-raspberrypi-dev`
(adba061), `rdke-generic-manifest` 1.1.1, `build-scripts` 1.0.5,
`meta-stack-layering-support` 5.0.4, all on github.com/rdkcentral;
`meta-raspberrypi` (kirkstone); and `qemuarm64.conf` and `qemu.inc` of
RDK's fork of poky (`rdk-4.7.0`). Lines taken from RDK's files keep their
meaning and are marked with where they are from.
