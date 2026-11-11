# Measurement procedures

How performance results are produced, so that a result from one host can be
compared with a result from another. The workloads are defined in
[workloads.json](workloads.json) and the combinations to cover in
[matrix.json](matrix.json).

## Rules for every measurement

1. **One combination at a time.** A run measures one host, one host CPU
   architecture and one emulator mode (`container`, `vm-native`, `vm-arm32`,
   `vm-arm64`).
2. **Fixed emulator size.** 4 CPUs and 2048 MiB of memory (the launcher's
   defaults) unless the result is explicitly about another size. In container
   mode the container engine must have at least that much; the engine's own
   CPU count and memory are recorded with the result.
3. **Quiet host.** Mains power, no other emulator or build running, and
   nothing else competing for the CPU or disk.
4. **Current image.** The launcher rebuilds the client OS image when its
   definition has changed. Never measure with a hand-modified image.
5. **Three runs, report the median.** Start the emulator fresh for each run
   (`--repeat 3`). Each run is recorded separately; the comparison uses the
   median of each test and shows the spread.
6. **Record, do not transcribe.** Results are written by the launcher
   (`--record`) to `evaluation/results/`. Numbers are never typed in by hand.
7. **Unavailable is a result.** When a combination or test cannot be run,
   that is stated with the reason. A test that fails inside the target
   reports `"value": null` and an `"unavailable"` reason. Nothing is
   estimated or carried over from another combination.
8. **Same workload version.** Only results from the same workload version
   are compared. A workload's version changes when its method changes.

## What identifies a result

Every record in `evaluation/results/` carries:

| Field | Identifies |
|---|---|
| `host` | host OS and version, CPU architecture, CPU model, CPU count, memory |
| `emulator` | mode and variant, guest architecture, accelerator, CPU model, runtime and its version, CPUs, memory, options |
| `image` | client OS image name and version, its source (Debian release, base image digest, apt snapshot), the SHA-256 of its build definition, the repository revision it was built from, and the SHA-256 of the root filesystem or the container image ID; plus what the running target reported about itself |
| `workload` | workload id, version and arguments |
| `boot_seconds` | time from starting the emulator until the target OS reported ready |

`./emu verify results` fails if any record lacks one of these.

## Resource benchmarks

Workload `bench` (CPU, memory allocation, memory bandwidth, I/O).

    ./emu run --mode container --workload bench --record --repeat 3
    ./emu run --mode vm --arch native --workload bench --record --repeat 3
    ./emu run --mode vm --arch arm64 --workload bench --record --repeat 3
    ./emu run --mode vm --arch arm32 --workload bench --record --repeat 3

- Every test runs for a fixed wall-clock time (2 seconds by default,
  `--seconds`), so the suite takes about as long under CPU emulation as it
  does natively.
- I/O tests run on `/data`, the target's writable data partition. In VM mode
  that is an ext4 filesystem on a virtio disk backed by a raw file on the
  host, formatted at boot. In container mode it is a volume of the container
  engine. The I/O results therefore describe the emulator's storage path, not
  the host disk alone.
- Reads use `O_DIRECT` so the target's page cache is not what is measured;
  each I/O result says whether direct I/O was in effect.

## Functional checks

Workload `prompt` starts an interactive shell on the target OS. The automated
check types a command into it and expects the computed answer back
(`./emu verify prompt-container prompt-vm`).

## Driver strategies

Workload `driver-check` reads a driver feature through its target OS
interface and reports what it observed (`./emu verify drivers-container
drivers-vm`). For `hwrng` the check proves which strategy served the read:

- `mocked`: the 16-byte sample equals the stub's fixed pattern.
- `host`: the sample appears in the byte stream the host-side process logged.
- `emulated`: no host-side process ran, and the target names the emulated
  provider (the kernel's virtio-rng driver in VM mode, the software device
  model in container mode).

## Graphics

Defined for stage 3. Each graphics technology (Wayland, OpenGL ES, Vulkan,
Flutter) renders a fixed scene at 720p, 1080p and 4K for a fixed time. Each
result records whether graphics were mapped to host acceleration or emulated.

## Audio and video decoding

Defined for stage 4. Fixed reference streams, one per codec and container, are
decoded as fast as possible (decode speed) and played in real time (dropped
frames). The reference streams are versioned with the workload.

## Web

Defined for stage 5. WPE WebKit plays a reference stream through MSE and
renders a fixed animated page.
