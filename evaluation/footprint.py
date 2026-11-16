#!/usr/bin/env python3
"""Values for evaluation/footprint.md that the repository's own files hold.

    python3 evaluation/footprint.py times [--host ID]
    python3 evaluation/footprint.py sizes

`times` adds up how long the recorded performance runs took, for every host
that has records in evaluation/results (or the one named): each record has
its run's `duration_seconds`, from the launch to the emulator's exit, the
target's start (`boot_seconds`) included. Per host and mode it prints, for
each workload, the median of its runs, the sum of those medians (one run of
each workload), and the number and the total of all recorded runs.

Where a host has recorded a workload more than three times, the median is of
the runs of the newest workload version that had the graphics provider of the
most recent one (emulated, or the host's GPU); the others count in the total
only.

`sizes` prints the size of each target that is built on this host: the VM
images from their manifests in build/vm, the container image as the container
engine lists it.

Nothing here measures: the values are sums of what is recorded or built.
"""
import argparse
import json
import pathlib
import statistics
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evaluation" / "results"
MODES = ("container", "vm-native", "vm-arm64", "vm-arm32")


def _version(text):
    return tuple(int(part) if part.isdigit() else 0 for part in str(text or "0").split("."))


def _records(host):
    found = []
    for path in sorted(RESULTS.glob("*.json")):
        try:
            with open(path) as handle:
                record = json.load(handle)
        except ValueError:
            continue
        if not isinstance(record, dict) or "duration_seconds" not in record or "emulator" not in record:
            continue        # the machines and the known issues are kept there too
        if host and record["host"]["id"] != host:
            continue
        found.append(record)
    return found


def _provider(record):
    return (record["emulator"].get("graphics") or {}).get("provider")


def _seconds(value):
    if value is None:
        return "–"
    return "%.0f s" % value if value < 120 else "%.1f min" % (value / 60.0)


def times(args):
    records = _records(args.host)
    if not records:
        print("no result records%s in %s" % (" of " + args.host if args.host else "", RESULTS.relative_to(ROOT)))
        return 1
    workloads = []
    for record in records:
        if record["workload"]["id"] not in workloads:
            workloads.append(record["workload"]["id"])
    for host in sorted({record["host"]["id"] for record in records}):
        mine = [record for record in records if record["host"]["id"] == host]
        dates = sorted(record["recorded_at"][:10] for record in mine)
        images = sorted({record["image"]["version"] for record in mine}, key=_version)
        print("### %s\n" % host)
        print("%d recorded runs, %s to %s, images %s.\n" % (len(mine), dates[0], dates[-1], ", ".join(images)))
        print("| Mode | %s | One run of each | Recorded runs | Their total | Of that, the target's start |" % " | ".join(workloads))
        print("|---|%s" % ("---|" * (len(workloads) + 4)))
        for mode in MODES:
            runs = [record for record in mine if record["emulator"]["variant"] == mode]
            if not runs:
                print("| %s |%s – | 0 | – | – |" % (mode, " – |" * len(workloads)))
                continue
            cells, medians = [], []
            for workload in workloads:
                of_workload = [record for record in runs if record["workload"]["id"] == workload]
                newest = max((_version(record["workload"].get("version")) for record in of_workload), default=None)
                chosen = [record for record in of_workload if _version(record["workload"].get("version")) == newest]
                if chosen:
                    latest = max(chosen, key=lambda record: record["recorded_at"])
                    chosen = [record for record in chosen if _provider(record) == _provider(latest)]
                durations = [record["duration_seconds"] for record in chosen if record.get("duration_seconds")]
                if not durations:
                    cells.append("–")
                    medians.append(None)
                    continue
                medians.append(statistics.median(durations))
                cells.append("%s (%d)" % (_seconds(medians[-1]), len(durations)))
            total = sum(record.get("duration_seconds") or 0 for record in runs)
            boot = sum(record.get("boot_seconds") or 0 for record in runs)
            one = sum(medians) if all(median is not None for median in medians) else None
            print("| %s | %s | %s | %d | %s | %s |" % (mode, " | ".join(cells), _seconds(one), len(runs),
                                                    _seconds(total), _seconds(boot)))
        print()
    print("A workload's column is the median of its runs, with their number in brackets.")
    return 0


def _bytes(count):
    return "%.2f GB" % (count / 1e9) if count >= 1e9 else "%.0f MB" % (count / 1e6)


def sizes(args):
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    from emulator import host, image
    print("Targets built on %s, image %s:\n" % (host.host_id(), image.definition()["version"]))
    found = False
    for arch in image.ARCHS:
        manifest = image.load_manifest("vm", arch)
        if not manifest or not manifest.get("files"):
            continue
        found = True
        files = manifest["files"]
        print("VM image, %s (%s%s, built %s): %s" % (
            arch, manifest.get("version"), "" if image.is_current(manifest) else ", not the current definition",
            manifest.get("built_at"), _bytes(sum(entry["bytes"] for entry in files.values()))))
        for name, entry in files.items():
            print("    %-12s %s" % (name, _bytes(entry["bytes"])))
    for arch in image.ARCHS:
        manifest = image.load_manifest("container", arch)
        if not manifest:
            continue
        found = True
        tag = manifest["image_tag"]
        cli = host.find_tool("docker") or host.find_tool("podman")
        size = None
        if cli:
            asked = subprocess.run([cli, "image", "ls", "--format", "{{.Size}}", tag], capture_output=True,
                                   text=True, env=host.tool_env())
            if asked.returncode == 0 and asked.stdout.strip():
                size = asked.stdout.strip().splitlines()[0]
        print("Container image, %s (%s%s, built %s): %s" % (
            arch, tag, "" if image.is_current(manifest) else ", not the current definition", manifest.get("built_at"),
            size + ", as the container engine lists it (`image ls`)" if size else "the container engine does not have it"))
    if not found:
        print("none: ./emu build builds them")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    timed = commands.add_parser("times", help="add up the recorded performance runs' durations")
    timed.add_argument("--host", metavar="ID", help="one host, such as macos-arm64 (default: every host with records)")
    timed.set_defaults(function=times)
    sized = commands.add_parser("sizes", help="the sizes of the targets built on this host")
    sized.set_defaults(function=sizes)
    args = parser.parse_args()
    return args.function(args)


if __name__ == "__main__":
    sys.exit(main())
