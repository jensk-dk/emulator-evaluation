"""Verification checks for the delivery stages.

Each check launches the real emulator on this host and asserts on what the
target OS reported. Outcomes are merged into
evaluation/verification/HOST.json, which records what has been verified on
which host.
"""
import datetime
import json
import tempfile
import time

from . import catalog, container, drivers as driver_features, graphics, host, image, results, vm
from .errors import EmuError
from .paths import VERIFICATION_DIR
from .run import RunOptions, launch

MOCK_PATTERN_HEX = b"MOCKED-HWRNG-V1.".hex()
# CPU part numbers the target reads from its own CPU ID register.
CPU_PART = {"cortex-a53": "0xd03", "cortex-a15": "0xc0f"}
QUICK_BENCH = ["--seconds", "0.5", "--io-mb", "32", "--mem-mb", "16"]


class CheckFailed(Exception):
    pass


class CheckUnavailable(Exception):
    """The check needs something this host does not have. That is recorded as
    its own outcome, with the reason: neither a pass nor a failure."""


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


# ------------------------------------------------------------ graphics ---

NATIVE_TECHNOLOGIES = ("wayland", "gles", "vulkan")
TECHNOLOGY_NAMES = {"wayland": "Wayland", "gles": "OpenGL ES", "vulkan": "Vulkan", "flutter": "Flutter"}
_demo_runs = {}
cut_runs = set()        # runs whose display capture showed only part of the display


def _demo(mode, arch, resolution, provider=None):
    """Run the graphics demo once per configuration and evaluate every test:
    it produced a frame rate at the selected resolution, and a capture of the
    emulator's display shows the frame it drew. Returns (emulator record,
    {technology: (problem or None, summary line, result)})."""
    key = (mode, arch, resolution, provider)
    if key in _demo_runs:
        return _demo_runs[key]
    width, height = graphics.resolution(resolution)
    technologies = NATIVE_TECHNOLOGIES + ("flutter",)
    with tempfile.TemporaryDirectory(prefix="emu-verify-") as shots:
        opts, outcome = _run(mode=mode, arch=arch, workload="graphics-demo", args=["--seconds", "1"],
                             resolution=resolution, graphics=provider, screenshot_dir=shots,
                             screenshot_format="ppm", timeout=3600)
        evaluation = {}
        for technology in technologies:
            result = next((r for r in outcome.results if r.get("technology") == technology), None)
            screen = next((c for c in outcome.screens if c.get("technology") == technology), None)
            problem = None
            if result is None:
                problem = "the %s test reported nothing" % technology
            elif result.get("value") is None:
                problem = "%s is unavailable: %s" % (TECHNOLOGY_NAMES[technology], result.get("unavailable"))
            elif result.get("resolution") != "%dx%d" % (width, height):
                problem = "%s rendered at %s, not %dx%d" % (technology, result.get("resolution"), width, height)
            elif screen is None:
                problem = "the frame of the %s test was not captured from the display" % technology
            else:
                # Only the capture of a display rendered on the host GPU may be
                # cut off; _resolutions then confirms the whole frame otherwise.
                host_rendered = outcome.environment["emulator"]["graphics"]["provider"] == "host"
                cut = host_rendered and graphics.capture_is_cut(screen, width, height)
                found = graphics.capture_problems(screen, width, height, allow_cut=host_rendered)
                if found:
                    problem = "%s at %dx%d: %s" % (technology, width, height, "; ".join(found))
            line = None
            if not problem:
                line = "%s at %dx%d: %.1f frames/s on %s; the display capture is %dx%d and shows %s" % (
                    TECHNOLOGY_NAMES[technology], width, height, result["value"], result.get("renderer"),
                    screen["captured_width"], screen["captured_height"],
                    "the top left part of its frame (QEMU's capture of a display rendered on the host GPU "
                    "reaches no further)" if cut else "its frame")
                if cut:
                    cut_runs.add(key)
            evaluation[technology] = (problem, line, result)
    _demo_runs[key] = (outcome.environment["emulator"], evaluation)
    return _demo_runs[key]


def _technologies(mode, arch, resolution, technologies, provider=None):
    emulator, evaluation = _demo(mode, arch, resolution, provider)
    lines = []
    for technology in technologies:
        problem, line, _ = evaluation[technology]
        _require(not problem, problem)
        lines.append(line)
    return emulator, evaluation, lines


def _guest_arch(mode, arch):
    return host.host_arch() if mode == "container" or arch == "native" else arch


def _technology(technology, mode, arch="native"):
    """One graphics technology renders and reaches the display, at 720p."""
    if technology == "flutter":
        flutter = image.definition()["source"]["flutter"]
        guest = _guest_arch(mode, arch)
        _require(guest in flutter["architectures"],
                 "the %s target image has no Flutter workload: the Flutter SDK (%s) builds Linux applications for "
                 "%s only" % (guest, flutter["version"], " and ".join(flutter["architectures"])))
    emulator, evaluation, lines = _technologies(mode, arch, "720p", (technology,))
    result = evaluation[technology][2]
    if technology == "flutter":
        lines.append("%s; frame build p99 %.1f ms, raster p99 %.1f ms" % (
            result.get("api"), result["build_time_ms"]["p99"], result["raster_time_ms"]["p99"]))
    else:
        lines.append("%s; frame time p99 %.1f ms" % (result.get("api"), result["frame_time_ms"]["p99"]))
    return lines + ["graphics provider: %s" % emulator["graphics"]["provider"]]


def _resolutions(mode, arch="native"):
    """Every supported resolution is rendered and shown, with each graphics
    technology that works in this mode at all. A technology that does not is
    reported by its own check, and named here as not covered."""
    _, evaluation = _demo(mode, arch, "720p")
    working = tuple(t for t in NATIVE_TECHNOLOGIES + ("flutter",) if not evaluation[t][0])
    _require("wayland" in working, evaluation["wayland"][0])
    lines = []
    for name in graphics.RESOLUTIONS:
        lines += _technologies(mode, arch, name, working)[2]
        if (mode, arch, name, None) in cut_runs:
            # The whole frame is confirmed where the capture reaches all of
            # it: with the display rendered by the target CPU.
            lines += ["with emulated graphics, for the whole frame: " + line
                      for line in _technologies(mode, arch, name, working, provider="emulated")[2]]
    missing = [TECHNOLOGY_NAMES[t] for t in NATIVE_TECHNOLOGIES + ("flutter",) if t not in working]
    if missing:
        lines.append("not covered, because unavailable in this mode: %s" % ", ".join(missing))
    return lines


def _probe(mode):
    """Whether this host has host graphics acceleration for the mode."""
    if mode == "vm":
        return graphics.probe_vm(host.require_tool(vm.QEMU_BINARY[host.host_arch()], "VM mode"))
    runtime = container.detect()
    manifest = image.ensure("container", lambda: runtime, host.host_arch(), quiet=True)
    return graphics.probe_container(runtime, manifest["image_tag"], manifest["platform"])


def _software(result):
    return result.get("accelerated") is False


def _graphics_emulated(mode):
    """Emulation is available: when asked for, and as the fallback of auto."""
    emulator, evaluation, lines = _technologies(mode, "native", "720p", ("gles", "vulkan"), provider="emulated")
    _require(emulator["graphics"]["provider"] == "emulated", "emulation was requested but not selected")
    for technology in ("gles", "vulkan"):
        _require(_software(evaluation[technology][2]),
                 "%s was not rendered by the target CPU: %s" % (technology, evaluation[technology][2].get("renderer")))
    lines = ["requested emulation: " + line for line in lines]
    probe = _probe(mode)
    auto, auto_evaluation, _ = _technologies(mode, "native", "720p", ("gles", "vulkan"))
    if probe["available"]:
        lines.append("auto did not need the fallback here: host acceleration is available")
    else:
        _require(auto["graphics"]["provider"] == "emulated", "auto selected %r although host acceleration is "
                 "unavailable" % auto["graphics"]["provider"])
        for technology in ("gles", "vulkan"):
            _require(_software(auto_evaluation[technology][2]), "auto fell back but %s was not rendered by the "
                     "target CPU" % technology)
        lines.append("auto fell back to emulation: " + auto["graphics"]["reason"])
    return lines


def _graphics_host(mode):
    """Graphics are mapped to host acceleration, and auto prefers it."""
    probe = _probe(mode)
    if not probe["available"]:
        # Asking for host acceleration must be refused, not silently emulated.
        try:
            launch(RunOptions(mode=mode, workload="graphics-demo", graphics="host", echo=False, quiet_build=True))
        except EmuError as error:
            raise CheckUnavailable("%s. Asking for it is refused: %s" % (probe["reason"], error))
        raise CheckFailed("--graphics host was accepted although this host has no host graphics acceleration")
    emulator, evaluation, lines = _technologies(mode, "native", "720p", ("gles",), provider="host")
    _require(emulator["graphics"]["provider"] == "host", "host acceleration was requested but not selected")
    _require(evaluation["gles"][2].get("accelerated") is True,
             "OpenGL ES was not rendered by the host GPU: %s" % evaluation["gles"][2].get("renderer"))
    auto, auto_evaluation, _ = _technologies(mode, "native", "720p", ("gles",))
    _require(auto["graphics"]["provider"] == "host", "auto did not prefer the available host acceleration")
    _require(auto_evaluation["gles"][2].get("accelerated") is True, "auto chose host acceleration but OpenGL ES "
             "was rendered by %s" % auto_evaluation["gles"][2].get("renderer"))
    vulkan = evaluation.get("vulkan", (None, None, {}))[2] or {}
    lines.append("Vulkan: %s" % ("on the host GPU (%s)" % vulkan.get("renderer") if vulkan.get("accelerated")
                                 else "rendered by the target CPU (%s)" % vulkan.get("renderer")))
    return ["requested host acceleration: " + line for line in lines] + ["auto preferred host acceleration: "
                                                                        + auto["graphics"]["reason"]]


def _graphics_checks():
    variants = (("container", "container", "native", "container mode"),
                ("vm", "vm", "native", "a host-native VM"),
                ("vm-arm64", "vm", "arm64", "an ARM64 VM"),
                ("vm-arm32", "vm", "arm32", "an ARM32 VM"))
    checks = {}
    for technology in NATIVE_TECHNOLOGIES + ("flutter",):
        for suffix, mode, arch, where in variants:
            checks["%s-%s" % (technology, suffix)] = (
                lambda t=technology, m=mode, a=arch: _technology(t, m, a), "4.1",
                "a %s workload renders in %s" % (TECHNOLOGY_NAMES[technology], where))
    for mode, where in (("container", "container mode"), ("vm", "VM mode")):
        checks["graphics-emulated-" + mode] = (lambda m=mode: _graphics_emulated(m), "4.2",
                                               "graphics are emulated on request and as the fallback, in " + where)
        checks["graphics-host-" + mode] = (lambda m=mode: _graphics_host(m), "4.2",
                                           "graphics are mapped to host acceleration and preferred, in " + where)
    for suffix, mode, arch, where in variants:
        checks["resolution-" + suffix] = (lambda m=mode, a=arch: _resolutions(m, a), "4.3",
                                          "720p, 1080p and 4K are rendered and displayed in " + where)
    return checks


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
CHECKS.update(_graphics_checks())


def _report_path():
    return VERIFICATION_DIR / ("%s.json" % host.host_id())


def load_report():
    try:
        with open(_report_path()) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"host": host.describe(), "checks": {}}


def run_checks(names):
    """Run the named checks; returns how many ended in each status."""
    report = load_report()
    report["host"] = host.describe()
    # Outcomes of checks that no longer exist say nothing about this revision.
    report["checks"] = {name: entry for name, entry in report["checks"].items() if name in CHECKS}
    counts = {"pass": 0, "fail": 0, "unavailable": 0}
    for name in names:
        function, task, description = CHECKS[name]
        print("%-26s %s" % (name, description), flush=True)
        started = time.time()
        try:
            details = function()
            status = "pass"
        except CheckUnavailable as error:
            details = str(error).splitlines()
            status = "unavailable"
        except (CheckFailed, EmuError) as error:
            details = str(error).splitlines()
            status = "fail"
        counts[status] += 1
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
    return counts
