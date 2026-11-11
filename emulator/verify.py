"""Verification checks for the delivery stages.

Each check launches the real emulator on this host and asserts on what the
target OS reported. Outcomes are merged into
evaluation/verification/HOST.json, which records what has been verified on
which host.
"""
import datetime
import json
import time

from . import catalog, drivers as driver_features, host, image, results, vm
from .paths import VERIFICATION_DIR
from .run import RunOptions, launch

MOCK_PATTERN_HEX = b"MOCKED-HWRNG-V1.".hex()
# CPU part numbers the target reads from its own CPU ID register.
CPU_PART = {"cortex-a53": "0xd03", "cortex-a15": "0xc0f"}
QUICK_BENCH = ["--seconds", "0.5", "--io-mb", "32", "--mem-mb", "16"]


class CheckFailed(Exception):
    pass


def _require(condition, message):
    if not condition:
        raise CheckFailed(message)


def _run(**kwargs):
    kwargs.setdefault("echo", False)
    kwargs.setdefault("quiet_build", True)
    kwargs.setdefault("timeout", 900)
    opts = RunOptions(**kwargs)
    outcome = launch(opts)
    if not outcome.ok:
        tail = "\n".join(outcome.output[-15:])
        raise CheckFailed("%s workload %r did not finish cleanly (exit %s, emulator exit %s%s)\n%s" % (
            outcome.environment["emulator"]["variant"], opts.workload, outcome.exit_code, outcome.process_exit,
            ", timed out" if outcome.timed_out else "", tail))
    _require(not outcome.protocol_errors, "garbled protocol lines: %r" % outcome.protocol_errors[:2])
    return opts, outcome


def _prompt(mode, arch="native", extra_script=b""):
    """Type a command into the interactive prompt and expect its answer."""
    script = b"echo emu-prompt-$((6*7))-ok\n" + extra_script + b"exit\n"
    opts, outcome = _run(mode=mode, arch=arch, workload="prompt", stdin_script=script)
    _require(outcome.ready is not None, "the target OS never reported ready")
    _require(any("emu-prompt-42-ok" in line for line in outcome.output),
             "the prompt did not answer the command typed into it")
    return outcome


def check_matrix():
    problems = catalog.verify_matrix()
    _require(not problems, "; ".join(problems))
    data = catalog.matrix()
    return ["%d hosts x %d modes = %d combinations, each measuring %d performance areas" % (
        len(data["hosts"]), len(data["modes"]), len(catalog.combinations(data)), len(data["performance_areas"])),
        "every declared host combination has a host entry: " + ", ".join(h["id"] for h in data["hosts"])]


def check_workloads():
    problems = catalog.verify_workloads()
    _require(not problems, "; ".join(problems))
    data = catalog.workloads()["workloads"]
    lines = []
    for area in catalog.PERFORMANCE_AREAS:
        owners = sorted({"%s %s (%s)" % (w["id"], w["version"], w["status"]) for w in data
                         for m in w.get("measurements", []) if m["area"] == area})
        lines.append("%s: %s" % (area, ", ".join(owners)))
    return lines


def check_image():
    """The client OS image boots in VM mode and its revision is recorded."""
    outcome = _prompt("vm")
    manifest = image.load_manifest("vm", host.host_arch())
    _require(manifest is not None, "no manifest for the VM image")
    for field in ("definition_sha256", "build_revision", "kernel_release"):
        _require(manifest.get(field), "the image manifest lacks %s" % field)
    source = manifest["source"]
    _require(source.get("base_image_digest") and source.get("apt_snapshot"),
             "the image source is not pinned (base image digest and apt snapshot)")
    reported = outcome.ready.get("image") or {}
    _require(reported.get("definition_sha256") == manifest["definition_sha256"],
             "the running target reports a different image definition than the manifest")
    _require(outcome.ready["kernel"] == manifest["kernel_release"], "the running kernel is not the image's kernel")
    return ["%s %s booted in %.1fs, kernel %s" % (manifest["name"], manifest["version"], outcome.boot_seconds,
                                                  manifest["kernel_release"]),
            "source: %s, %s@%s, apt snapshot %s" % (source["distribution"], source["base_image"],
                                                    source["base_image_digest"][:19], source["apt_snapshot"]),
            "definition %s, build revision %s, rootfs sha256 %s" % (
                manifest["definition_sha256"][:12], manifest["build_revision"],
                manifest["files"]["rootfs.img"]["sha256"][:12])]


def check_prompt_container():
    outcome = _prompt("container")
    _require(outcome.ready["mode"] == "container", "the target did not start in container mode")
    return ["target OS environment up in %.1fs; the prompt answered a typed command" % outcome.boot_seconds,
            "image %s" % outcome.environment["image"]["image_id"]]


def check_prompt_vm():
    outcome = _prompt("vm")
    emulator = outcome.environment["emulator"]
    _require(outcome.ready["mode"] == "vm", "the target did not start in VM mode")
    _require(emulator["guest_arch"] == host.host_arch(), "host-native mode ran a different architecture")
    native = vm.NATIVE_ACCELERATOR[host.host_os()]
    _require(emulator["accelerator"] == native,
             "host-native mode ran on %s instead of the host hypervisor (%s)" % (emulator["accelerator"], native))
    return ["booted on %s (%s, cpu %s) in %.1fs; the prompt answered a typed command" % (
        emulator["accelerator"], outcome.ready["machine"], emulator["cpu_model"], outcome.boot_seconds)]


def _bench(mode):
    opts, outcome = _run(mode=mode, workload="bench", args=QUICK_BENCH)
    areas = {r["area"] for r in outcome.results if r.get("value") is not None}
    for area in ("cpu", "memory_allocation", "memory_bandwidth", "io"):
        _require(area in areas, "no %s measurement was produced" % area)
    unavailable = [r["test"] for r in outcome.results if r.get("value") is None]
    _require(not unavailable, "tests reported unavailable: %s" % ", ".join(unavailable))
    record = results.build(outcome, opts)
    missing = results.missing_identity(record)
    _require(not missing, "the result record lacks identity fields: %s" % ", ".join(missing))
    return ["%d measurements across %s" % (len(outcome.results), ", ".join(sorted(areas))),
            "record identifies host %s, mode %s, image %s %s, workload %s %s" % (
                record["host"]["id"], record["emulator"]["variant"], record["image"]["name"],
                record["image"]["version"], record["workload"]["id"], record["workload"]["version"])]


def check_bench_container():
    return _bench("container")


def check_bench_vm():
    return _bench("vm")


def check_results():
    """Every recorded result names its environment and covers the stage 1 areas."""
    records = results.load_all()
    _require(records, "no results have been recorded in evaluation/results/")
    lines = []
    seen = {}
    for path, record in records:
        missing = results.missing_identity(record)
        _require(not missing, "%s lacks identity fields: %s" % (path.name, ", ".join(missing)))
        if record["workload"]["id"] == "bench" and record["host"]["id"] == host.host_id():
            seen.setdefault(record["emulator"]["variant"], set()).update(
                r["area"] for r in record["results"] if r.get("value") is not None)
    for variant in ("container", "vm-native"):
        for area in ("cpu", "memory_allocation", "memory_bandwidth", "io"):
            _require(area in seen.get(variant, ()),
                     "no recorded %s result for %s on this host" % (area, variant))
    lines.append("%d records, all fully identified" % len(records))
    lines.append("this host has bench results for: " + ", ".join(sorted(seen)))
    return lines


def _vm_arch(arch, machine):
    outcome = _prompt("vm", arch, extra_script=b"grep -m1 -i 'cpu part' /proc/cpuinfo\n")
    emulator = outcome.environment["emulator"]
    _require(outcome.ready["machine"] == machine,
             "the target reports machine %s, expected %s" % (outcome.ready["machine"], machine))
    part = CPU_PART[emulator["cpu_model"]]
    _require(any("CPU part" in line and part in line for line in outcome.output),
             "the target does not see a %s CPU (part %s)" % (emulator["cpu_model"], part))
    return ["%s guest on %s simulating %s (CPU part %s) booted in %.1fs and ran the prompt workload" % (
        machine, emulator["accelerator"], emulator["cpu_model"], part, outcome.boot_seconds)]


def check_vm_arm32():
    return _vm_arch("arm32", "armv7l")


def check_vm_arm64():
    return _vm_arch("arm64", "aarch64")


def _drivers(mode, arch="native"):
    lines = []
    for strategy in driver_features.STRATEGIES:
        opts, outcome = _run(mode=mode, arch=arch, workload="driver-check", args=["hwrng"],
                             drivers={"hwrng": strategy})
        _require(len(outcome.results) == 1 and outcome.results[0].get("ok"), "the hwrng read failed")
        result = outcome.results[0]
        sample = result["sample_hex"]
        provider = result.get("provider") or ""
        trace = outcome.host_traces.get("hwrng", "")
        _require(result["strategy"] == strategy, "the target started strategy %r" % result["strategy"])
        if strategy == "mocked":
            _require(sample == MOCK_PATTERN_HEX, "the sample is not the stub's pattern: %s" % sample)
            _require(provider.startswith("mock:"), "unexpected provider %r" % provider)
            proof = "sample is the stub's fixed pattern"
        elif strategy == "host":
            _require(outcome.environment["host_processes"], "no host-side process ran")
            _require(sample in trace, "the sample is not in the bytes the host-side process served")
            expected = "kernel:virtio_rng" if mode == "vm" else "host:"
            _require(provider.startswith(expected), "unexpected provider %r" % provider)
            proof = "sample found in the %d bytes served by the host-side process" % (len(trace) // 2)
        else:
            _require(not outcome.environment["host_processes"], "a host-side process ran")
            _require(sample != MOCK_PATTERN_HEX, "the sample is the stub's pattern")
            expected = "kernel:virtio_rng" if mode == "vm" else "model:"
            _require(provider.startswith(expected), "unexpected provider %r" % provider)
            proof = "no host-side process ran"
        lines.append("%s: %s; provider %s; %s bytes/s" % (strategy, proof, provider.split(" ")[0],
                                                           result.get("throughput_bytes_per_second")))
    return lines


def check_drivers_container():
    return _drivers("container")


def check_drivers_vm():
    return _drivers("vm")


def check_drivers_vm_arm32():
    return _drivers("vm", "arm32")


def check_drivers_vm_arm64():
    return _drivers("vm", "arm64")


# name -> (function, the task in openspec/changes/staged-emulator-delivery/tasks.md it supports, description)
CHECKS = {
    "matrix": (check_matrix, "1.1", "the host test matrix covers every declared host combination"),
    "image": (check_image, "1.2", "the client OS image boots in VM mode and its revision is recorded"),
    "workloads": (check_workloads, "1.3", "the workloads cover every required performance area"),
    "prompt-container": (check_prompt_container, "2.2, 2.3", "the container image starts the target OS and a prompt"),
    "prompt-vm": (check_prompt_vm, "2.2, 2.4", "the target OS boots in host-native VM mode to a prompt"),
    "bench-container": (check_bench_container, "2.5", "CPU, memory and I/O workloads run in container mode"),
    "bench-vm": (check_bench_vm, "2.5", "CPU, memory and I/O workloads run in host-native VM mode"),
    "results": (check_results, "2.5", "recorded results carry their environment identity"),
    "vm-arm32": (check_vm_arm32, "3.1", "ARM32 VM guest mode starts the target OS workload"),
    "vm-arm64": (check_vm_arm64, "3.1", "ARM64 VM guest mode starts the target OS workload"),
    "drivers-container": (check_drivers_container, "3.2", "emulated, mocked and host-routed drivers in container mode"),
    "drivers-vm": (check_drivers_vm, "3.2", "emulated, mocked and host-routed drivers in host-native VM mode"),
    "drivers-vm-arm32": (check_drivers_vm_arm32, "3.2", "the three driver strategies in an ARM32 VM"),
    "drivers-vm-arm64": (check_drivers_vm_arm64, "3.2", "the three driver strategies in an ARM64 VM"),
}


def _report_path():
    return VERIFICATION_DIR / ("%s.json" % host.host_id())


def load_report():
    try:
        with open(_report_path()) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"host": host.describe(), "checks": {}}


def run_checks(names):
    """Run the named checks; returns the number that failed."""
    report = load_report()
    report["host"] = host.describe()
    failed = 0
    for name in names:
        function, task, description = CHECKS[name]
        print("%-18s %s" % (name, description), flush=True)
        started = time.time()
        try:
            details = function()
            status = "pass"
        except CheckFailed as error:
            details = str(error).splitlines()
            status = "fail"
            failed += 1
        print("  %s (%.1fs)" % (status.upper(), time.time() - started))
        for line in details:
            print("    " + line)
        report["checks"][name] = {
            "status": status,
            "task": task,
            "description": description,
            "details": details,
            "checked_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "seconds": round(time.time() - started, 1),
            "revision": image.git_revision(),
            "image_definition_sha256": image.definition_sha256(),
        }
        VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
        with open(_report_path(), "w") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
    return failed
