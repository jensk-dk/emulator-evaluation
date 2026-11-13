"""Verification checks for the delivery stages.

Each check launches the real emulator on this host and asserts on what the
target OS reported. Outcomes are merged into
evaluation/verification/HOST.json, which records what has been verified on
which host.
"""
import datetime
import json
import os
import subprocess
import tempfile
import threading
import time

from . import catalog, container, drivers as driver_features, graphics, host, hostaudio, image, results, vm
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


# --------------------------------------------------------------- media ---

CONTAINER_NAMES = {"mp2ts": "MP2TS", "mp4": "MP4", "fragments": "MSE-style fragments"}
VIDEO_CODECS = {"mpeg2": "MPEG-2", "avc": "AVC", "hevc": "HEVC"}
AUDIO_CODECS = {"mp2": "MP2", "ac3": "AC-3", "aac": "AAC", "heaac": "HE-AAC"}
TONE_HZ = {"mp2": 440, "ac3": 660, "aac": 880, "heaac": 1100}       # target/media/build-media.sh
LOUD = 1000.0       # a window of sound at this level or above holds a test tone
_media_runs = {}


def _media_decoding(mode, arch):
    """Decode every reference stream once per configuration; returns the
    results by test and case."""
    key = (mode, arch)
    if key not in _media_runs:
        _, outcome = _run(mode=mode, arch=arch, workload="media-decode", args=["--tests", "video,audio"],
                          drivers=driver_features.parse(["audio=none"]), timeout=7200)
        _media_runs[key] = {(r["test"], r["case"]): r for r in outcome.results}
    return _media_runs[key]


def _decoded(found, test, case):
    result = found.get((test, case))
    _require(result is not None, "the %s test reported nothing for %s" % (test, case))
    _require(result.get("value") is not None, "%s was not decoded: %s" % (case, result.get("unavailable")))
    return result


def _media_input(mode, arch="native"):
    """Media is accepted in each container, and as injected fragments."""
    found = _media_decoding(mode, arch)
    lines = []
    for container_id, name in CONTAINER_NAMES.items():
        speeds = []
        for codec, codec_name in VIDEO_CODECS.items():
            result = _decoded(found, "video_decode_speed", "%s-%s" % (codec, container_id))
            if container_id == "fragments":
                _require(result.get("fragments_appended", 0) > 0 and result.get("bytes_appended", 0) > 0,
                         "no fragments were appended for %s" % result["case"])
                speeds.append("%s from %d fragments appended to the decoder (%d bytes)" % (
                    codec_name, result["fragments_appended"], result["bytes_appended"]))
            else:
                speeds.append("%s %d frames" % (codec_name, result["frames"]))
        lines.append("%s accepted: %s" % (name, ", ".join(speeds)))
    for case in ("audio-mp2-mp2ts", "audio-heaac-mp2ts", "audio-aac-mp4", "audio-heaac-mp4"):
        _decoded(found, "audio_decode_speed", case)
    lines.append("audio-only streams accepted in MP2TS and in MP4")
    return lines


def _media_codecs(mode, arch="native"):
    """Every required video and audio codec is decoded."""
    found = _media_decoding(mode, arch)
    lines = []
    for codec, name in VIDEO_CODECS.items():
        speeds = [_decoded(found, "video_decode_speed", "%s-%s" % (codec, c)) for c in CONTAINER_NAMES]
        lines.append("%s video: %d frames of %s decoded at %s x realtime (%s; %s)" % (
            name, speeds[0]["frames"], speeds[0]["resolution"],
            ", ".join("%.1f" % r["value"] for r in speeds), ", ".join(CONTAINER_NAMES.values()), speeds[0]["decoder"]))
    for codec, name in AUDIO_CODECS.items():
        cases = [r for (test, _), r in found.items() if test == "audio_decode_speed" and r["audio_codec"] == codec]
        _require(cases, "no %s stream was decoded" % name)
        for result in cases:
            _require(result.get("value") is not None, "%s was not decoded: %s" % (result["case"],
                                                                                   result.get("unavailable")))
        lines.append("%s audio: decoded at %s x realtime" % (name, ", ".join("%.0f" % r["value"] for r in cases)))
    return lines


_video_runs = {}


def _video(technology, mode, arch="native"):
    """Decoded video is rendered through one graphics technology and reaches
    the display, for each video codec."""
    if technology == "flutter":
        flutter = image.definition()["source"]["flutter"]
        guest = _guest_arch(mode, arch)
        _require(guest in flutter["architectures"],
                 "the %s target image has no Flutter application: the Flutter SDK (%s) builds Linux applications "
                 "for %s only" % (guest, flutter["version"], " and ".join(flutter["architectures"])))
    key = (mode, arch)
    if key not in _video_runs:
        width, height = graphics.resolution("720p")
        with tempfile.TemporaryDirectory(prefix="emu-verify-") as shots:
            _, outcome = _run(mode=mode, arch=arch, workload="media-decode", args=["--tests", "playback"],
                              resolution="720p", screenshot_dir=shots, screenshot_format="ppm",
                              options={"audio-output": "none"}, timeout=7200)
            evaluation = {}
            host_rendered = outcome.environment["emulator"]["graphics"]["provider"] == "host"
            for result in outcome.results:
                screen = next((c for c in outcome.screens if c.get("case") == result["case"]), None)
                if result.get("value") is None:
                    problem = "%s was not played: %s" % (result["case"], result.get("unavailable"))
                elif screen is None:
                    problem = "%s was not captured from the display" % result["case"]
                else:
                    found = graphics.capture_problems(screen, width, height, allow_cut=host_rendered,
                                                      tolerance=graphics.VIDEO_COLOR_TOLERANCE)
                    problem = "%s: %s" % (result["case"], "; ".join(found)) if found else None
                evaluation[result["case"]] = (problem, result)
        _video_runs[key] = (outcome.environment["emulator"], evaluation)
    emulator, evaluation = _video_runs[key]
    mine = {case: item for case, item in evaluation.items() if case.endswith("/" + technology)}
    _require(mine, "no stream was played through %s" % technology)
    lines = []
    for case, (problem, result) in mine.items():
        _require(not problem, problem)
        lines.append("%s from %s: played on %s, %d of %d frames dropped; a capture of the display shows the video%s"
                     % (VIDEO_CODECS[result["video_codec"]], CONTAINER_NAMES[result["container"]],
                        result.get("renderer"), result["value"], result["frames"],
                        " (the display service ended during the first attempt and was started again)"
                        if result.get("display_restarts") else ""))
    return lines + ["graphics provider: %s; sound: %s" % (emulator["graphics"]["provider"],
                                                          next(iter(mine.values()))[1].get("audio"))]


class _HostSink:
    """A private output device of the host's sound server, with a recording
    of everything played on it: the check hears what the host OS was given,
    and nothing comes out of the loudspeakers. Linux with PulseAudio or
    PipeWire; elsewhere `reason` says why there is none."""

    def __init__(self):
        self.name = None
        self.reason = None
        self._module = None
        self._recorder = None
        self._file = None
        pactl, parec = host.find_tool("pactl"), host.find_tool("parec")
        if host.host_os() != "linux" or not pactl or not parec:
            self.reason = "no recording at the host's sound server: that needs pactl and parec (PulseAudio or " \
                          "PipeWire on a Linux host)"
            return
        name = "emu-verify-%d-%d" % (os.getpid(), int(time.time() * 1000) % 100000)
        done = subprocess.run([pactl, "load-module", "module-null-sink", "sink_name=" + name,
                               "sink_properties=device.description=" + name], capture_output=True, text=True)
        if done.returncode != 0 or not done.stdout.strip().isdigit():
            self.reason = "no recording at the host's sound server: it gave no private output device (%s)" \
                          % (done.stderr.strip() or done.stdout.strip())
            return
        self._pactl, self._module, self.name = pactl, done.stdout.strip(), name
        self._file = tempfile.NamedTemporaryFile(prefix="emu-verify-", suffix=".raw")
        self._recorder = subprocess.Popen([parec, "--device=%s.monitor" % name, "--raw", "--format=s16le",
                                           "--rate=%d" % hostaudio.RATE, "--channels=%d" % hostaudio.CHANNELS],
                                          stdout=self._file, stderr=subprocess.DEVNULL)

    def options(self):
        return {"audio-sink": self.name} if self.name else {"audio-output": "none"}

    def close(self):
        """Stop recording; returns the (level, pitch) of each tenth of a second."""
        windows = []
        if self._recorder:
            time.sleep(0.5)     # what the player still holds
            self._recorder.terminate()
            self._recorder.wait()
            with open(self._file.name, "rb") as handle:
                data = handle.read()
            self._file.close()
            step = hostaudio.WINDOW_BYTES
            windows = [hostaudio.measure(data[start:start + step]) for start in range(0, len(data) - step + 1, step)]
        if self._module:
            subprocess.run([self._pactl, "unload-module", self._module], capture_output=True)
        return windows


def _trace(outcome):
    return [json.loads(line) for line in outcome.host_traces.get("audio", "").splitlines() if line.strip()]


def _tone_windows(windows, hz):
    """How many windows hold a tone of this pitch."""
    return sum(1 for level, pitch in windows if level >= LOUD and abs(pitch - hz) <= hz * 0.05)


def _audio_host(mode, arch="native"):
    """Decoded audio of every codec is played through the host OS."""
    sink = _HostSink()
    try:
        _, outcome = _run(mode=mode, arch=arch, workload="media-decode", args=["--tests", "sound"],
                          drivers=driver_features.parse(["audio=host"]), options=sink.options(), timeout=3600)
    finally:
        heard = sink.close()
    audio = outcome.environment["emulator"].get("audio") or {}
    _require(outcome.environment["host_processes"], "no host-side audio process ran")
    received = [(row["level"], row["hz"]) for row in _trace(outcome)]
    lines = []
    for result in outcome.results:
        _require(result.get("value") is not None, "%s was not played: %s" % (result["case"], result.get("unavailable")))
    for codec, name in AUDIO_CODECS.items():
        hz = TONE_HZ[codec]
        took = [r["value"] for r in outcome.results if r["audio_codec"] == codec]
        _require(took, "no %s stream was played" % name)
        _require(_tone_windows(received, hz) >= 5, "the host-side process did not receive the %d Hz tone of the %s "
                 "stream" % (hz, name))
        line = "%s: played on the target in %s s; its %d Hz tone reached the host-side process" % (
            name, ", ".join("%.1f" % value for value in took), hz)
        if sink.name:
            _require(_tone_windows(heard, hz) >= 5, "the %d Hz tone of the %s stream was not played on the host's "
                     "output device" % (hz, name))
            line += " and was recorded at the host's sound server"
        lines.append(line)
    lines.append("path: target ALSA device (%s) -> %s -> %s" % (
        next((d.get("provider") for d in outcome.drivers if d.get("feature") == "audio"), "?"), audio.get("path"),
        "the host's player program (%s)" % audio.get("player") if sink.name else "no host output in this check"))
    if not sink.name:
        raise CheckUnavailable("\n".join(lines + [sink.reason]))
    return lines


def _audio_mute(mode):
    """The emulator's audio is muted and unmuted while a stream plays."""
    sink = _HostSink()
    switched = []

    def switch(info):
        """Once the tone is playing, mute it for two seconds."""
        def run():
            deadline = time.time() + 1800
            while time.time() < deadline:
                try:
                    with open(info["trace"]) as handle:
                        loud = sum(1 for line in handle if json.loads(line)["level"] >= LOUD)
                except (OSError, ValueError):
                    loud = 0
                if loud >= 15:
                    break
                time.sleep(0.1)
            else:
                return
            for command, pause in (("mute", 2.0), ("unmute", 0.0)):
                try:
                    switched.append((command, hostaudio.control(info["control_port"], command)["muted"]))
                except (OSError, ValueError, KeyError) as error:
                    switched.append((command, "failed: %s" % error))
                time.sleep(pause)
        threading.Thread(target=run, daemon=True).start()

    try:
        _, outcome = _run(mode=mode, workload="media-decode",
                          args=["--tests", "sound", "--streams", "audio-aac-mp4", "--sound-seconds", "7"],
                          drivers=driver_features.parse(["audio=host"]), options=sink.options(), on_audio=switch,
                          timeout=3600)
    finally:
        heard = sink.close()
    _require(switched == [("mute", True), ("unmute", False)], "the mute switch did not answer as expected: %r"
             % (switched,))
    rows = [row for row in _trace(outcome) if row["level"] >= LOUD]
    # The sound as it arrived never stops; what is sent on does, while muted.
    phases = []
    for row in rows:
        state = "silent" if row["sent_level"] < hostaudio.SILENT_RMS else "sound"
        if not phases or phases[-1][0] != state:
            phases.append([state, 0])
        phases[-1][1] += 1
    summary = ", ".join("%s for %.1f s" % (state, count / 10) for state, count in phases)
    _require([state for state, _ in phases] == ["sound", "silent", "sound"] and all(count >= 5 for _, count in phases),
             "the sound sent to the host was not: sound, silence while muted, sound again (it was: %s)" % summary)
    lines = ["while the target played a %d Hz tone for %.1f s, the sound sent to the host was: %s" % (
        TONE_HZ["aac"], len(rows) / 10, summary)]
    if not sink.name:
        raise CheckUnavailable("\n".join(lines + [sink.reason]))
    # The same at the host's sound server: tone, a silent stretch, tone again.
    loud = [index for index, (level, pitch) in enumerate(heard)
            if level >= LOUD and abs(pitch - TONE_HZ["aac"]) <= TONE_HZ["aac"] * 0.05]
    _require(len(loud) >= 10, "the tone was not played on the host's output device")
    gap = max((b - a - 1 for a, b in zip(loud, loud[1:])), default=0)
    _require(15 <= gap <= 30, "the recording at the host's sound server has no silent stretch of about two seconds "
             "inside the tone (longest: %.1f s)" % (gap / 10))
    lines.append("recorded at the host's sound server: the tone, %.1f s of silence, the tone again" % (gap / 10))
    return lines


def _audio_strategies(mode):
    """The emulated and the mocked audio device take sound at its own pace,
    without the host."""
    lines = []
    for strategy, expected in (("emulated", "kernel:" if mode == "vm" else "model:"), ("mocked", "mock:")):
        _, outcome = _run(mode=mode, workload="media-decode",
                          args=["--tests", "sound", "--streams", "audio-mp2-mp2ts", "--sound-seconds", "2"],
                          drivers=driver_features.parse(["audio=" + strategy]), timeout=3600)
        _require(not any(p.get("feature") == "audio" for p in outcome.environment["host_processes"]),
                 "a host-side audio process ran")
        result = outcome.results[0]
        _require(result.get("value") is not None, "the sound was not played: %s" % result.get("unavailable"))
        provider = result.get("device") or ""
        _require(provider.startswith(expected), "unexpected audio device %r" % provider)
        _require(result["value"] >= 1.8, "2 s of sound were taken in %.2f s: the device does not keep time"
                 % result["value"])
        lines.append("%s: 2 s of sound played in %.1f s on %s; no host-side process ran" % (
            strategy, result["value"], provider))
    return lines


def _media_checks():
    variants = (("container", "container", "native", "container mode"),
                ("vm", "vm", "native", "a host-native VM"),
                ("vm-arm64", "vm", "arm64", "an ARM64 VM"),
                ("vm-arm32", "vm", "arm32", "an ARM32 VM"))
    checks = {}
    for suffix, mode, arch, where in variants:
        checks["media-input-" + suffix] = (lambda m=mode, a=arch: _media_input(m, a), "5.1",
                                           "MP2TS, MP4 and MSE-style fragments are accepted in " + where)
        checks["media-codecs-" + suffix] = (lambda m=mode, a=arch: _media_codecs(m, a), "5.2",
                                            "MPEG-2, AVC, HEVC, MP2, AC-3, AAC and HE-AAC are decoded in " + where)
    for technology in NATIVE_TECHNOLOGIES + ("flutter",):
        for suffix, mode, arch, where in variants:
            checks["video-%s-%s" % (technology, suffix)] = (
                lambda t=technology, m=mode, a=arch: _video(t, m, a), "5.3",
                "decoded video is rendered through %s in %s" % (TECHNOLOGY_NAMES[technology], where))
    for suffix, mode, arch, where in variants:
        checks["audio-host-" + suffix] = (lambda m=mode, a=arch: _audio_host(m, a), "5.3",
                                          "decoded audio is played through the host OS, from " + where)
    for mode, where in (("container", "container mode"), ("vm", "VM mode")):
        checks["audio-mute-" + mode] = (lambda m=mode: _audio_mute(m), "5.3",
                                        "audio is muted and unmuted while it plays, in " + where)
        checks["audio-strategies-" + mode] = (lambda m=mode: _audio_strategies(m), "3.2, 5.3",
                                              "the emulated and mocked audio devices in " + where)
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
CHECKS.update(_media_checks())


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
