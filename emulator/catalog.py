"""The evaluation's test matrix and workload definitions, and the checks
that keep them complete."""
import json
import re

from .paths import EVALUATION_DIR, TARGET_DIR

PERFORMANCE_AREAS = ("cpu", "memory_allocation", "memory_bandwidth", "io", "graphics", "audio_video_decoding")
HOST_OPERATING_SYSTEMS = ("linux", "macos", "windows")
VM_GUEST_ARCHS = ("native", "arm32", "arm64")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def matrix():
    with open(EVALUATION_DIR / "matrix.json") as handle:
        return json.load(handle)


def workloads():
    with open(EVALUATION_DIR / "workloads.json") as handle:
        return json.load(handle)


def workload(workload_id):
    for item in workloads()["workloads"]:
        if item["id"] == workload_id:
            return item
    return None


def combinations(data=None):
    """Every host and emulator-mode combination the evaluation must cover."""
    data = data or matrix()
    excluded = {(item["host"], item["mode"]) for item in data.get("exclusions", [])}
    return [(h, m) for h in data["hosts"] for m in data["modes"] if (h["id"], m["id"]) not in excluded]


def verify_matrix():
    """Problems with the test matrix; empty when it is complete."""
    data = matrix()
    problems = []
    hosts = data["hosts"]
    pairs = [(h["os"], h["arch"]) for h in hosts]
    ids = [h["id"] for h in hosts]
    if len(set(ids)) != len(ids) or len(set(pairs)) != len(pairs):
        problems.append("hosts are not unique")
    for system in HOST_OPERATING_SYSTEMS:
        if system not in [h["os"] for h in hosts]:
            problems.append("no host entry for required host OS %r" % system)
    for declared in data["declared_host_combinations"]:
        if (declared["os"], declared["arch"]) not in pairs:
            problems.append("declared host combination %s/%s has no host entry" % (declared["os"], declared["arch"]))
    for pair in pairs:
        if pair not in [(d["os"], d["arch"]) for d in data["declared_host_combinations"]]:
            problems.append("host %s/%s is not a declared combination" % pair)
    for h in hosts:
        if not h.get("native_accelerator"):
            problems.append("host %s names no hardware accelerator for host-native VM mode" % h["id"])

    modes = data["modes"]
    if not any(m["mode"] == "container" for m in modes):
        problems.append("no container mode")
    vm_archs = sorted(m["guest_arch"] for m in modes if m["mode"] == "vm")
    if vm_archs != sorted(VM_GUEST_ARCHS):
        problems.append("VM modes cover guest architectures %s, expected %s" % (vm_archs, sorted(VM_GUEST_ARCHS)))
    if sorted(data["performance_areas"]) != sorted(PERFORMANCE_AREAS):
        problems.append("performance areas differ from the required set")
    for exclusion in data.get("exclusions", []):
        if not exclusion.get("reason"):
            problems.append("exclusion %s/%s has no reason" % (exclusion.get("host"), exclusion.get("mode")))
    expected = len(hosts) * len(modes) - len(data.get("exclusions", []))
    if len(combinations(data)) != expected:
        problems.append("exclusions name combinations that do not exist")
    return problems


def _source_version(item):
    """The version a workload's implementation reports about itself."""
    source = item.get("version_source")
    if not source:
        return None
    text = (TARGET_DIR.parent / source["file"]).read_text()
    match = re.search(source["pattern"], text)
    return match.group(1) if match else None


def verify_workloads():
    """Problems with the workload definitions; empty when they are complete."""
    data = workloads()
    problems = []
    ids = [w["id"] for w in data["workloads"]]
    if len(set(ids)) != len(ids):
        problems.append("workload ids are not unique")
    covered = set()
    for item in data["workloads"]:
        label = "workload %s" % item["id"]
        if not _SEMVER.match(item.get("version", "")):
            problems.append("%s has no MAJOR.MINOR.PATCH version" % label)
        if item.get("status") not in ("implemented", "defined"):
            problems.append("%s has no status (implemented or defined)" % label)
        if not item.get("procedure"):
            problems.append("%s names no measurement procedure" % label)
        for measurement in item.get("measurements", []):
            for field in ("area", "test", "unit", "method"):
                if not measurement.get(field):
                    problems.append("%s: a measurement lacks %r" % (label, field))
            if measurement.get("area") in PERFORMANCE_AREAS:
                covered.add(measurement["area"])
            elif item.get("kind") == "performance":
                problems.append("%s: unknown performance area %r" % (label, measurement.get("area")))
        if item.get("kind") == "performance" and not item.get("measurements"):
            problems.append("%s defines no measurements" % label)
        if item.get("status") == "implemented":
            if not (TARGET_DIR / "rootfs" / "opt" / "emu" / "workloads" / item["id"]).is_file():
                problems.append("%s is marked implemented but is not in the target image" % label)
            reported = _source_version(item)
            if item.get("version_source") and reported != item["version"]:
                problems.append("%s declares version %s but its implementation reports %s"
                                % (label, item["version"], reported))
    for area in PERFORMANCE_AREAS:
        if area not in covered:
            problems.append("no workload measures performance area %r" % area)
    return problems
