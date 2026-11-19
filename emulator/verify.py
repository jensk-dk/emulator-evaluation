"""Verification checks for the delivery stages.

Each check launches the real emulator on this host and asserts on what the
target OS reported. Outcomes are merged into
evaluation/verification/HOST.json, which records what has been verified on
which host.
"""
import contextlib
import datetime
import http.client
import io
import json
import os
import queue
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

from . import armtargets, catalog, container, drivers as driver_features, graphics, host, hostaudio, image, \
    imagefile, redrat, remote, report, results, vm, window
from .errors import EmuError
from .paths import EVALUATION_DIR, RESULTS_DIR, ROOT, VERIFICATION_DIR
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
            "record identifies host %s on machine %s, mode %s, image %s %s, workload %s %s" % (
                record["host"]["id"], record["host"]["machine"], record["emulator"]["variant"], record["image"]["name"],
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
        if record["workload"]["id"] == "bench" and host.host_key(record["host"]) == host.host_key():
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
    """Where a check hears what the host OS was given to play, without a
    sound from the loudspeakers. `where` names the place; `reason` says why
    there is none on this host.

    Linux, with PulseAudio or PipeWire: a private output device of the sound
    server, and a recording of everything played on it.

    macOS: the default output device, played at volume 0. The launcher's
    player records what the system's audio queue takes for the device, which
    happens at the device's own pace, and the system's audio server is asked
    whether it sees the player playing."""

    def __init__(self):
        self.name = None
        self.reason = None
        self.where = "the host's sound server"
        self.activity = None        # macOS and Windows: what the audio server said about the player
        self._module = None
        self._recorder = None
        self._file = None
        self._monitor = None
        if host.host_os() in hostaudio.OWN_PLAYER_HOSTS:
            if host.host_os() == "macos":
                try:
                    self._player = [host.macos_audio_player()]
                except EmuError as error:
                    self.reason = "no recording at the host's audio output: %s" % error
                    return
            else:
                self._player = [sys.executable, "-m", "emulator.winmm_player"]
                found, why = hostaudio.find_player("windows", None)
                if not found:
                    self.reason = "no recording at the host's audio output: %s" % why
                    return
            handle, self._monitor = tempfile.mkstemp(prefix="emu-verify-", suffix=".raw")
            os.close(handle)
            self.name = "the default output device, at volume 0"
            self.where = "the host's audio output"
            return
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
        if self._monitor:
            return {"audio-volume": "0", "audio-monitor": self._monitor}
        return {"audio-sink": self.name} if self.name else {"audio-output": "none"}

    def watch(self, info):
        """macOS and Windows: while the sound plays, ask the system's audio server what it
        sees of the player process. Called with the audio process's details."""
        if not self._monitor:
            return

        def run():
            deadline = time.time() + 1800
            while time.time() < deadline:
                time.sleep(0.5)
                try:
                    pid = hostaudio.control(info["control_port"], "status").get("player_pid")
                except (OSError, ValueError):
                    return          # the audio process has ended
                if not pid:
                    continue
                try:
                    done = subprocess.run(self._player + ["activity", str(pid)], capture_output=True, text=True,
                                          timeout=20, cwd=str(ROOT),
                                          env=host.tool_env({"PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}))
                    found = json.loads(done.stdout)
                except (OSError, ValueError, subprocess.SubprocessError):
                    continue
                self.activity = found
                if found.get("playing") or found.get("known") is None:
                    return
        threading.Thread(target=run, daemon=True).start()

    def close(self):
        """Stop recording; returns the (level, pitch) of each tenth of a second."""
        windows = []
        data = b""
        if self._recorder:
            time.sleep(0.5)     # what the player still holds
            self._recorder.terminate()
            self._recorder.wait()
            with open(self._file.name, "rb") as handle:
                data = handle.read()
            self._file.close()
        if self._monitor:
            # The player ends when the audio process does, and then writes its summary.
            deadline = time.time() + 5
            while not os.path.exists(self._monitor + ".json") and time.time() < deadline:
                time.sleep(0.1)
            try:
                with open(self._monitor, "rb") as handle:
                    data = handle.read()
                with open(self._monitor + ".json") as handle:
                    self.summary = json.load(handle)
            except (OSError, ValueError):
                self.summary = {}
            for path in (self._monitor, self._monitor + ".json"):
                try:
                    os.unlink(path)
                except OSError:
                    pass
        step = hostaudio.WINDOW_BYTES
        windows = [hostaudio.measure(data[start:start + step]) for start in range(0, len(data) - step + 1, step)]
        if self._module:
            subprocess.run([self._pactl, "unload-module", self._module], capture_output=True)
        return windows

    def evidence(self):
        """macOS and Windows: what the output device and the audio server said, as lines
        for the check's report; problems raise CheckFailed."""
        if not self._monitor:
            return []
        summary = getattr(self, "summary", {})
        _require(summary.get("started"), "the host's output device did not start playing")
        _require(summary.get("device_clock_seconds", 0) >= 0.8 * summary.get("sound_seconds", 0) > 0,
                 "the host's output device did not play the sound it was given (%.1f s played of %.1f s)"
                 % (summary.get("device_clock_seconds", 0), summary.get("sound_seconds", 0)))
        lines = ["host output device: %s, at volume %d; it played for %.1f s by its own clock, %.1f s of that the "
                 "target's sound" % (summary.get("device"), summary.get("volume", 0),
                                     summary["device_clock_seconds"], summary["sound_seconds"])]
        if self.activity and self.activity.get("known"):
            _require(self.activity.get("playing"), "the host's audio server did not see the player playing")
            lines.append("the host's audio server reported the player process as playing on: %s"
                         % ", ".join(self.activity.get("devices") or ["(no device named)"]))
        elif self.activity:
            lines.append("the host's audio server gave no process report (%s)" % self.activity.get("reason"))
        return lines


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
                          drivers=driver_features.parse(["audio=host"]), options=sink.options(),
                          on_audio=sink.watch, timeout=3600)
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
            line += " and was recorded at %s" % sink.where
        lines.append(line)
    lines.append("path: target ALSA device (%s) -> %s -> %s" % (
        next((d.get("provider") for d in outcome.drivers if d.get("feature") == "audio"), "?"), audio.get("path"),
        "the host's player program (%s)" % audio.get("player") if sink.name else "no host output in this check"))
    if not sink.name:
        raise CheckUnavailable("\n".join(lines + [sink.reason]))
    return lines + sink.evidence()


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
    _require(15 <= gap <= 30, "the recording at %s has no silent stretch of about two seconds "
             "inside the tone (longest: %.1f s)" % (sink.where, gap / 10))
    lines.append("recorded at %s: the tone, %.1f s of silence, the tone again" % (sink.where, gap / 10))
    return lines + sink.evidence()


def _audio_switch(mode):
    """A run that starts muted, and the launcher's command for the switch:
    its state, and toggling it, for one named run."""
    from .cli import _running_audio
    launcher = [sys.executable, "-m", "emulator", "audio"]
    environment = host.tool_env({"PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"})
    said = []
    run = {}

    def command(action):
        done = subprocess.run(launcher + [action, "--run", run["id"]], capture_output=True, text=True, timeout=60,
                              cwd=str(ROOT), env=environment, stdin=subprocess.DEVNULL)
        return done.returncode, (done.stdout + done.stderr).strip()

    def switch(info):
        """Once the tone has arrived for a while: the state, the switch
        turned for two seconds, turned back, and the state again."""
        def work():
            mine = [item["run_id"] for item in _running_audio() if item.get("control_port") == info["control_port"]]
            if not mine:
                return
            run["id"] = mine[0]
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
            for action, pause in (("status", 0.0), ("toggle", 2.0), ("toggle", 1.0), ("status", 0.0)):
                said.append((action,) + command(action))
                time.sleep(pause)
        threading.Thread(target=work, daemon=True).start()

    # The sound is taken in and not played: the switch is in the run's audio
    # process, which records what it would send on.
    _, outcome = _run(mode=mode, workload="media-decode",
                      args=["--tests", "sound", "--streams", "audio-aac-mp4", "--sound-seconds", "7"],
                      drivers=driver_features.parse(["audio=host"]), options={"audio-output": "none"}, muted=True,
                      on_audio=switch, timeout=3600)
    _require(run.get("id"), "the launcher's audio command would not have found the run: it left no note of its "
             "audio process")

    def state(text):
        return "not muted" if ": not muted;" in text else "muted" if ": muted;" in text else None
    failed = [(action, status, text) for action, status, text in said if status != 0]
    _require(len(said) == 4 and not failed, "the audio command did not answer four times with success: %r" % (said,))
    states = [state(text) for _, _, text in said]
    _require(states == ["muted", "not muted", "muted", "muted"],
             "started muted, then asked for the state, toggled twice and asked again, the command said: %r" % (said,))
    rows = [row for row in _trace(outcome) if row["level"] >= LOUD]
    phases = []
    for row in rows:
        now = "silent" if row["sent_level"] < hostaudio.SILENT_RMS else "sound"
        if not phases or phases[-1][0] != now:
            phases.append([now, 0])
        phases[-1][1] += 1
    summary = ", ".join("%s for %.1f s" % (now, count / 10) for now, count in phases)
    _require([now for now, _ in phases] == ["silent", "sound", "silent"] and all(count >= 5 for _, count in phases),
             "the sound sent on to the host was not: silence from the start, sound after the first toggle, silence "
             "after the second (it was: %s)" % summary)
    status, text = command("status")
    _require(status != 0, "asked for a run that has ended, the audio command reported success: %s" % text)
    return ["started with the mute setting, the run was muted from its first sound: while the target played a "
            "%d Hz tone for %.1f s, the sound sent on to the host was: %s" % (TONE_HZ["aac"], len(rows) / 10, summary),
            "the launcher's audio command, for this run by its id: state \"muted\"; toggle, \"not muted\"; toggle, "
            "\"muted\"; state \"muted\"",
            "its last answer: %s" % said[-1][2].split("): ", 1)[-1],
            "after the run had ended the command reported failure: %s" % text.splitlines()[0]]


def _audio_strategies(mode):
    """The emulated and the mocked audio device take sound at its own pace,
    without the host."""
    lines = []
    emulated = ("model:",)
    if mode == "vm":
        binary = host.require_tool(vm.QEMU_BINARY[host.host_arch()], "VM mode with the host's guest architecture")
        emulated = ("kernel:" if vm.has_device(binary, "virtio-sound-pci") else "model:",)
    for strategy, expected in (("emulated", emulated), ("mocked", ("mock:",))):
        _, outcome = _run(mode=mode, workload="media-decode",
                          args=["--tests", "sound", "--streams", "audio-mp2-mp2ts", "--sound-seconds", "2"],
                          drivers=driver_features.parse(["audio=" + strategy]), timeout=3600)
        _require(not any(p.get("feature") == "audio" for p in outcome.environment["host_processes"]),
                 "a host-side audio process ran")
        result = outcome.results[0]
        _require(result.get("value") is not None, "the sound was not played: %s" % result.get("unavailable"))
        provider = result.get("device") or ""
        _require(provider.startswith(expected), "unexpected audio device %r (expected one of %s)" %
                 (provider, ", ".join(expected)))
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
    for mode, where in (("container", "container mode"), ("vm", "VM mode")):
        checks["audio-switch-" + mode] = (lambda m=mode: _audio_switch(m), "9.2",
                                          "a run starts muted, and the audio command toggles it and says its "
                                          "state, in " + where)
    return checks


# ----------------------------------------------------------------- web ---

_web_runs = {}


def _web(mode, arch, tests):
    """Run the web workload once per configuration and set of tests, at 720p;
    returns (emulator record, workload announcement, {(test, case): (problem
    with its display capture or None, result)})."""
    key = (mode, arch, tests)
    if key not in _web_runs:
        width, height = graphics.resolution("720p")
        with tempfile.TemporaryDirectory(prefix="emu-verify-") as shots:
            _, outcome = _run(mode=mode, arch=arch, workload="web-bench", args=["--tests", tests, "--seconds", "2"],
                              resolution="720p", screenshot_dir=shots, screenshot_format="ppm",
                              options={"audio-output": "none"}, timeout=7200)
            host_rendered = outcome.environment["emulator"]["graphics"]["provider"] == "host"
            evaluation = {}
            for result in outcome.results:
                name = result.get("case") or result["test"]
                screen = next((c for c in outcome.screens if c.get("test") == result["test"]
                               and c.get("case") == result.get("case")), None)
                if result.get("value") is None:
                    problem = None      # reported by the check, with the workload's reason
                elif screen is None:
                    problem = "%s was not captured from the display" % name
                else:
                    video = result["test"] == "mse_playback_dropped_frames"
                    found = graphics.capture_problems(
                        screen, width, height, allow_cut=host_rendered,
                        tolerance=graphics.VIDEO_COLOR_TOLERANCE if video else graphics.COLOR_TOLERANCE)
                    problem = "%s: %s" % (name, "; ".join(found)) if found else None
                evaluation[(result["test"], result.get("case"))] = (problem, result)
        _web_runs[key] = (outcome.environment["emulator"], outcome.workload or {}, evaluation)
    return _web_runs[key]


def _web_result(evaluation, test, case=None):
    _require((test, case) in evaluation, "the web workload reported nothing for %s" % (case or test))
    problem, result = evaluation[(test, case)]
    _require(result.get("value") is not None, "%s is unavailable: %s" % (case or test, result.get("unavailable")))
    _require(not problem, problem)
    return result


def _web_launch(mode, arch="native"):
    """WPE WebKit starts in the target, loads a page and shows it."""
    emulator, _, evaluation = _web(mode, arch, "launch")
    result = _web_result(evaluation, "web_launch")
    _require("AppleWebKit" in (result.get("user_agent") or ""), "the page did not run in WebKit: %r"
             % result.get("user_agent"))
    _require(result.get("viewport") == result.get("resolution"), "the page was %s on a %s display"
             % (result.get("viewport"), result.get("resolution")))
    return ["%s started, loaded a page and ran its script in %.1f s; a capture of the display shows the page, "
            "full screen at %s" % (result.get("browser"), result["value"], result.get("resolution")),
            "Media Source Extensions: %s; drawn on %s" % ("available" if result.get("media_source") else "missing",
                                                          result.get("renderer")),
            "graphics provider: %s" % emulator["graphics"]["provider"]]


def _web_render(mode, arch="native"):
    """The animated page is rendered and reaches the display."""
    emulator, _, evaluation = _web(mode, arch, "render,mse")
    result = _web_result(evaluation, "web_render_fps")
    return ["the animated page at %s: %.1f frames/s in %s on %s; a capture of the display shows it" % (
        result.get("resolution"), result["value"], result.get("browser"), result.get("renderer")),
        "time between frames p99 %.1f ms" % result["frame_time_ms"]["p99"],
        "graphics provider: %s" % emulator["graphics"]["provider"]]


def _web_mse(mode, arch="native"):
    """Reference streams are played through MSE and the results recorded."""
    emulator, _, evaluation = _web(mode, arch, "render,mse")
    cases = [case for test, case in evaluation if test == "mse_playback_dropped_frames"]
    _require(cases, "no stream was played through MSE")
    lines = []
    for case in cases:
        result = _web_result(evaluation, "mse_playback_dropped_frames", case)
        _require(result.get("fragments_appended", 0) > 0, "no fragments were appended for %s" % case)
        _require(result.get("total_video_frames", 0) > 0, "the browser counted no video frames for %s" % case)
        _require(result.get("display_repaints") is not None,
                 "the result for %s does not say what the display showed" % case)
        lines.append("%s through MSE: %d fragments appended, %d of %d frames not shown (the browser counted %d at "
                     "its output and %d dropped; the display showed something new %d times), sound %s; a capture "
                     "of the display shows the video%s" % (
                         VIDEO_CODECS[result["video_codec"]], result["fragments_appended"], result["value"],
                         result["frames"], result["total_video_frames"], result.get("dropped_video_frames") or 0,
                         result["display_repaints"], result.get("sound"),
                         " (the display service ended during the first attempt and was started again)"
                         if result.get("display_restarts") else ""))
    result = evaluation[("mse_playback_dropped_frames", cases[0])][1]
    return lines + ["played by %s; graphics provider: %s" % (result.get("browser"), emulator["graphics"]["provider"])]


def _web_checks():
    variants = (("container", "container", "native", "container mode"),
                ("vm", "vm", "native", "a host-native VM"),
                ("vm-arm64", "vm", "arm64", "an ARM64 VM"),
                ("vm-arm32", "vm", "arm32", "an ARM32 VM"))
    checks = {}
    for suffix, mode, arch, where in variants:
        checks["web-launch-" + suffix] = (lambda m=mode, a=arch: _web_launch(m, a), "6.1",
                                          "WPE WebKit launches in " + where)
    for suffix, mode, arch, where in variants:
        checks["web-render-" + suffix] = (lambda m=mode, a=arch: _web_render(m, a), "6.2",
                                          "WPE WebKit renders the animated page in " + where)
        checks["web-mse-" + suffix] = (lambda m=mode, a=arch: _web_mse(m, a), "6.2",
                                       "WPE WebKit plays the reference streams through MSE in " + where)
    return checks



# ------------------------------------- display window, remote control keys ---

WINDOW_RESOLUTION = "720p"
KEYS_PICTURE_MARKER = (255, 0, 255)     # the block at the top centre of emukeys' picture
_window_runs = {}


def _picture_problems(path, width, height):
    """Whether a picture saved by the display window shows the target's
    picture (emukeys' marker blocks) at this size."""
    try:
        found = imagefile.size(path)
    except (OSError, ValueError) as error:
        return ["the picture could not be read: %s" % error]
    entry = {"file": path, "captured_width": found[0], "captured_height": found[1], "marker": KEYS_PICTURE_MARKER}
    return graphics.capture_problems(entry, width, height)


def _wait(condition, seconds, pause=0.2):
    deadline = time.time() + seconds
    while time.time() < deadline:
        found = condition()
        if found:
            return found
        time.sleep(pause)
    return condition()


def _drive_window(viewer, seen, width, height, directory):
    """What a person would do with the display window and the on-screen
    remote control, and what was observed each time (into `seen`)."""
    ask = viewer.ask
    state = _wait(lambda: (lambda s: s if s["connected"] and s["display"] == [width, height] else None)(ask(do="state")),
                  180)
    if not state:
        seen["error"] = "the window did not get the target's %dx%d display: %r" % (width, height, ask(do="state"))
        return
    seen["initial_remote_window"] = state["remote_window"]
    ratio = state["pixel_ratio"]

    def shown_picture(name):
        """Save the part of the window that shows the display; returns
        (state, problems of the picture)."""
        current = ask(do="state")
        path = os.path.join(directory, name + ".ppm")
        saved = ask(do="save-shown", path=path)
        if not saved.get("saved"):
            return current, ["the window could not save what it shows: %r" % saved]
        return current, _picture_problems(path, round(current["shown"][0] * ratio), round(current["shown"][1] * ratio))

    # The display as it arrived, pixel for pixel. The picture may be a
    # moment behind the display's size.
    path = os.path.join(directory, "display.ppm")
    problems = _wait(lambda: (ask(do="save-display", path=path), _picture_problems(path, width, height))[1] == [] or None,
                     120, 0.5)
    seen["display"] = {"problems": [] if problems else _picture_problems(path, width, height), "state": ask(do="state")}

    # Scaling: smaller with the display's shape, then a window of another shape.
    scaling = []
    for wanted in ([width // 2, height // 2], [900, 700]):
        ask(do="resize", display=wanted)
        scale = min(wanted[0] / width, wanted[1] / height)
        expected = [round(width * scale), round(height * scale)]
        _wait(lambda: ask(do="state")["widget"] == wanted, 10)
        time.sleep(0.5)
        current, problems = shown_picture("scaled-%dx%d" % tuple(wanted))
        scaling.append({"widget": current["widget"], "wanted": wanted, "shown": current["shown"], "expected": expected,
                        "problems": problems})
    seen["scaling"] = scaling

    # The toolbar: 1:1, then mute and unmute.
    ask(do="toolbar", action="one-to-one")
    _wait(lambda: ask(do="state")["widget"] == ask(do="state")["natural"], 10)
    time.sleep(0.5)
    current, problems = shown_picture("one-to-one")
    seen["one_to_one"] = {"widget": current["widget"], "natural": current["natural"], "shown": current["shown"],
                          "pixel_ratio": ratio, "toolbar": current["toolbar"], "problems": problems}
    mute = []
    port = (seen.get("audio") or {}).get("control_port")
    for _ in range(2):
        ask(do="toolbar", action="mute")
        time.sleep(0.3)
        try:
            switch = hostaudio.control(port, "status")["muted"] if port else None
        except (OSError, ValueError, KeyError) as error:
            switch = "no answer: %s" % error
        mute.append({"window": ask(do="state")["muted"], "switch": switch})
    seen["mute"] = mute

    # Full screen with the hotkey, and back with the other one.
    before = ask(do="state")
    ask(**{"do": "host-key", "key": "F", "with": ["ctrl", "alt"]})
    _wait(lambda: ask(do="state")["widget"] != before["widget"], 6)
    time.sleep(1.0)
    full, problems = shown_picture("full-screen")
    answer = ask(do="host-key", key="F11")
    if "error" in answer:
        raise CheckFailed("the window did not take the F11 key: %s" % answer["error"])
    _wait(lambda: ask(do="state")["widget"] == before["widget"], 6)
    time.sleep(1.0)
    after = ask(do="state")
    seen["full_screen"] = {"before": before, "full": full, "after": after, "problems": problems}

    # Every remote control key: by its host key, typed into the display
    # window, and by its button on the on-screen remote control.
    def press(command, code):
        with seen["lock"]:
            start = len(seen["keys"])
        ask(**command)
        wanted = [(code, "pressed"), (code, "released")]

        def arrived():
            with seen["lock"]:
                got = [(key["code"], key["state"]) for key in seen["keys"][start:]]
            return got if got[:2] == wanted or len(got) >= 2 else None
        got = _wait(arrived, 60, 0.05)
        with seen["lock"]:
            symbol = seen["keys"][start]["symbol"] if len(seen["keys"]) > start else None
        return {"code": code, "arrived": got, "ok": got == wanted, "symbol": symbol}

    # The toolbar's other two buttons: full screen (back with the hotkey,
    # since full screen has no toolbar), and the on-screen remote control.
    controls = {}
    before = ask(do="state")
    ask(do="toolbar", action="full-screen")
    _wait(lambda: ask(do="state")["full_screen"], 6)
    time.sleep(1.0)
    full = ask(do="state")
    ask(do="host-key", key="F11")
    _wait(lambda: ask(do="state")["widget"] == before["widget"], 6)
    time.sleep(1.0)
    controls["full_button"] = {"before": before, "full": full, "after": ask(do="state")}

    def remote_shown(command):
        """Whether the on-screen remote control is shown: as it is, and after
        the command given once and once more."""
        shown = [ask(do="state")["remote_window"]]
        for _ in range(2):
            ask(**command)
            time.sleep(0.3)
            shown.append(ask(do="state")["remote_window"])
        return shown
    controls["remote_button"] = remote_shown({"do": "toolbar", "action": "remote"})

    # The other hotkeys: the remote control, mute, and 1:1 from another size.
    controls["remote_hotkey"] = remote_shown({"do": "host-key", "key": "R", "with": ["ctrl", "alt"]})
    mute = []
    for _ in range(2):
        ask(**{"do": "host-key", "key": "M", "with": ["ctrl", "alt"]})
        time.sleep(0.3)
        try:
            switch = hostaudio.control(port, "status")["muted"] if port else None
        except (OSError, ValueError, KeyError) as error:
            switch = "no answer: %s" % error
        mute.append({"window": ask(do="state")["muted"], "switch": switch})
    controls["mute_hotkey"] = mute
    wanted = [width // 2, height // 2]
    ask(do="resize", display=wanted)
    _wait(lambda: ask(do="state")["widget"] == wanted, 10)
    resized = ask(do="state")
    ask(**{"do": "host-key", "key": "1", "with": ["ctrl", "alt"]})
    _wait(lambda: ask(do="state")["widget"] == ask(do="state")["natural"], 10)
    time.sleep(0.5)
    current, problems = shown_picture("one-to-one-hotkey")
    controls["one_hotkey"] = {"resized": resized["widget"], "widget": current["widget"], "natural": current["natural"],
                              "shown": current["shown"], "problems": problems}
    # No hotkey is a remote control key: the first key the target gets is
    # the one that is pressed now.
    controls["first_key"] = press({"do": "host-key", "key": "Return"}, remote.CODES["ok"])
    with seen["lock"]:
        controls["keys"] = [(key["code"], key["state"]) for key in seen["keys"]]
    seen["controls"] = controls

    ask(do="toolbar", action="remote")
    _wait(lambda: ask(do="state")["remote_window"], 5)
    seen["remote"] = ask(do="state")
    seen["host_keys"] = {}
    seen["buttons"] = {}
    for key, _, code, _ in remote.KEYS:
        seen["host_keys"][key] = dict(press({"do": "host-key", "key": remote.host_keys_of(key)[0]}, code),
                                      host=remote.host_keys_of(key)[0])
    for key, _, code, _ in remote.KEYS:
        if key in seen["remote"]["remote_buttons"]:
            seen["buttons"][key] = press({"do": "remote-click", "key": key}, code)
    # A host key typed while the remote control's window has the keyboard.
    seen["key_in_remote"] = press({"do": "host-key", "key": "Return", "in": "remote"}, remote.CODES["ok"])
    path = os.path.join(directory, "remote.ppm")
    seen["remote_picture"] = bool(ask(do="save-remote", path=path).get("saved")) and imagefile.size(path)


def _window_session(mode, arch):
    """One run with the display window and the on-screen remote control, on
    the remote-keys workload: its window shows a still picture with marker
    blocks and reports every key it gets. Returns what was observed."""
    key = (mode, arch)
    if key in _window_runs:
        return _window_runs[key]
    if not window.gui_python():
        raise CheckUnavailable("Qt for Python (%s) is not installed on this host, so the launcher has no windows; %s"
                               % (window.PACKAGE, host.SETUP_HINT))
    width, height = graphics.resolution(WINDOW_RESOLUTION)
    seen = {"keys": [], "lock": threading.Lock(), "ready": threading.Event()}

    def on_line(line):
        start = line.find("EMU-KEY: ")
        if start < 0:
            return
        try:
            data = json.loads(line[start + 9:])
        except ValueError:
            return
        if data.get("ready"):
            seen["ready"].set()
        elif "code" in data:
            with seen["lock"]:
                seen["keys"].append(data)

    def on_audio(info):
        seen["audio"] = info

    with tempfile.TemporaryDirectory(prefix="emu-verify-") as directory:
        def drive(viewer):
            def work():
                try:
                    if not seen["ready"].wait(1800):
                        seen["error"] = "the target's window never got the keyboard focus"
                        return
                    _drive_window(viewer, seen, width, height, directory)
                except Exception as error:      # reported by the checks, whatever it was
                    seen["error"] = "%s: %s" % (type(error).__name__, error)
                finally:
                    try:
                        viewer.ask(do="send-key", code=remote.END_KEY)
                    except (EmuError, OSError, ValueError):
                        pass
            threading.Thread(target=work, daemon=True).start()

        # The sound is taken in and not played: the window's mute button
        # needs the run's audio process, not its sound.
        _, outcome = _run(mode=mode, arch=arch, workload="remote-keys", resolution=WINDOW_RESOLUTION, window=True,
                          drivers=driver_features.parse(["audio=host"]),
                          options={"audio-output": "none"}, on_line=on_line, on_audio=on_audio, on_viewer=drive,
                          timeout=3600)
    seen["emulator"] = outcome.environment["emulator"]
    _window_runs[key] = seen
    return seen


def _window(mode, arch):
    seen = _window_session(mode, arch)
    _require("error" not in seen, seen.get("error"))
    return seen


def _window_display(mode, arch="native"):
    """The launcher's window shows the target's display."""
    seen = _window(mode, arch)
    display = seen["display"]
    _require(not display["problems"], "the display in the window is not the target's picture: %s"
             % "; ".join(display["problems"]))
    state = display["state"]
    _require(seen["emulator"]["display"].get("window") == graphics.LAUNCHER_WINDOW,
             "the display was not shown in the launcher's own window: %r" % seen["emulator"]["display"])
    return ["the window got the target's %dx%d display and shows its picture: the marker blocks are where the "
            "target drew them, pixel for pixel" % tuple(state["display"]),
            "windowed, with its toolbar; the display took %dx%d of the window at a pixel ratio of %s"
            % (state["shown"][0], state["shown"][1], state["pixel_ratio"]),
            "graphics provider: %s" % seen["emulator"]["graphics"]["provider"]]


def _kept_its_size(full):
    """What to say of a window that says it is full screen and did not grow.
    Seen on macOS with a window that the system has not made the active
    application, as it does not for one started from a session in the
    background."""
    return ("the window reported full screen but kept its size (%dx%d on a %dx%d screen): this host's window "
            "system did not carry the switch out%s. That the display fills the screen was not observed"
            % (full["window"][0], full["window"][1], full["screen"][0], full["screen"][1],
               "" if full["active"] else ", and had not made the window the active one"))


def _window_fullscreen(mode, arch="native"):
    """The hotkey switches the window to full screen and back."""
    seen = _window(mode, arch)
    found = seen["full_screen"]
    before, full, after = found["before"], found["full"], found["after"]
    _require(not before["full_screen"] and before["toolbar"], "the window did not start windowed with its toolbar")
    _require(full["full_screen"], "Ctrl+Alt+F did not switch the window to full screen")
    _require(not full["toolbar"], "the toolbar stayed up in full screen")
    _require(not after["full_screen"] and after["toolbar"], "F11 did not switch back to the window with its toolbar")
    _require(after["widget"] == before["widget"], "back from full screen the display has %r of the window, not %r "
             "as before" % (after["widget"], before["widget"]))
    lines = ["Ctrl+Alt+F: full screen, without the toolbar; F11: back to the %dx%d window with its toolbar"
             % tuple(before["window"])]
    if full["window"] != full["screen"]:
        raise CheckUnavailable("\n".join(lines + [_kept_its_size(full)]))
    _require(not found["problems"], "full screen does not show the target's picture: %s" % "; ".join(found["problems"]))
    return lines + ["full screen the window covered the %dx%d screen, and the display in it, scaled to %dx%d, "
                    "shows the target's picture" % (full["screen"][0], full["screen"][1], full["shown"][0],
                                                    full["shown"][1])]


def _window_scaling(mode, arch="native"):
    """The display scales with the window."""
    seen = _window(mode, arch)
    lines = []
    for step in seen["scaling"]:
        _require(step["widget"] == step["wanted"], "the window did not take the size %r (it has %r)"
                 % (step["wanted"], step["widget"]))
        _require(all(abs(a - b) <= 1 for a, b in zip(step["shown"], step["expected"])),
                 "in a %dx%d window the display is drawn %dx%d, not %dx%d"
                 % tuple(step["wanted"] + step["shown"] + step["expected"]))
        _require(not step["problems"], "the display scaled to %dx%d does not show the target's picture: %s"
                 % (step["shown"][0], step["shown"][1], "; ".join(step["problems"])))
        lines.append("window resized to %dx%d: the %s display is drawn %dx%d, all of it, in its own shape"
                     % (step["wanted"][0], step["wanted"][1], WINDOW_RESOLUTION, step["shown"][0], step["shown"][1]))
    return lines


def _window_toolbar(mode, arch="native"):
    """The toolbar's 1:1 and mute buttons."""
    seen = _window(mode, arch)
    one = seen["one_to_one"]
    width, height = graphics.resolution(WINDOW_RESOLUTION)
    _require(one["toolbar"], "the window has no toolbar")
    _require(one["widget"] == one["natural"] == one["shown"], "after 1:1 the display is drawn %r in a %r area, not %r"
             % (one["shown"], one["widget"], one["natural"]))
    _require([round(side * one["pixel_ratio"]) for side in one["shown"]] == [width, height],
             "1:1 draws the %dx%d display on %r pixels at a pixel ratio of %s"
             % (width, height, one["shown"], one["pixel_ratio"]))
    _require(not one["problems"], "at 1:1 the window does not show the target's picture: %s"
             % "; ".join(one["problems"]))
    _require(seen.get("audio"), "the run had no audio process for the mute button to switch")
    _require(seen["mute"] == [{"window": True, "switch": True}, {"window": False, "switch": False}],
             "the mute button did not mute and unmute the run's audio: %r" % (seen["mute"],))
    return ["1:1: the %dx%d display is drawn on %dx%d screen pixels, after the window had been another size"
            % (width, height, width, height),
            "mute: the button muted the run's audio process and then unmuted it (asked of the process itself each "
            "time)"]


def _window_buttons(mode, arch="native"):
    """The toolbar's buttons for full screen and for the on-screen remote control."""
    seen = _window(mode, arch)
    found = seen["controls"]
    _require(found["remote_button"] == [False, True, False],
             "the remote control button did not show and hide the initially hidden on-screen remote control: it was shown "
             "%r" % (found["remote_button"],))
    lines = ["the remote control button hid the on-screen remote control and showed it again"]
    step = found["full_button"]
    before, full, after = step["before"], step["full"], step["after"]
    _require(not before["full_screen"] and before["toolbar"], "the window was not windowed with its toolbar")
    _require(full["full_screen"], "the full screen button did not switch the window to full screen")
    _require(not full["toolbar"], "the toolbar stayed up in full screen")
    _require(not after["full_screen"] and after["toolbar"] and after["widget"] == before["widget"],
             "F11 did not bring the window back as it was, with its toolbar")
    lines.append("the full screen button: full screen, without the toolbar; F11 brought the %dx%d window back with "
                 "its toolbar" % tuple(before["window"]))
    if full["window"] != full["screen"]:
        raise CheckUnavailable("\n".join(lines + [_kept_its_size(full)]))
    return lines + ["full screen the window covered the %dx%d screen" % tuple(full["screen"])]


def _window_hotkeys(mode, arch="native"):
    """The hotkeys for mute, 1:1 and the on-screen remote control, and that
    no hotkey reaches the target."""
    seen = _window(mode, arch)
    found = seen["controls"]
    _require(found["remote_hotkey"] == [False, True, False],
             "Ctrl+Alt+R did not show and hide the initially hidden on-screen remote control: it was shown %r"
             % (found["remote_hotkey"],))
    _require(seen.get("audio"), "the run had no audio process for the mute hotkey to switch")
    _require(found["mute_hotkey"] == [{"window": True, "switch": True}, {"window": False, "switch": False}],
             "Ctrl+Alt+M did not mute and unmute the run's audio: %r" % (found["mute_hotkey"],))
    one = found["one_hotkey"]
    width, height = graphics.resolution(WINDOW_RESOLUTION)
    ratio = seen["one_to_one"]["pixel_ratio"]
    _require(one["resized"] != one["natural"], "the window did not take another size before Ctrl+Alt+1")
    _require(one["widget"] == one["natural"] == one["shown"], "after Ctrl+Alt+1 the display is drawn %r in a %r "
             "area, not %r" % (one["shown"], one["widget"], one["natural"]))
    _require([round(side * ratio) for side in one["shown"]] == [width, height],
             "Ctrl+Alt+1 draws the %dx%d display on %r pixels at a pixel ratio of %s"
             % (width, height, one["shown"], ratio))
    _require(not one["problems"], "after Ctrl+Alt+1 the window does not show the target's picture: %s"
             % "; ".join(one["problems"]))
    code = remote.CODES["ok"]
    _require(found["first_key"]["ok"], "the key pressed after the hotkeys did not reach the target: %r"
             % (found["first_key"],))
    _require([tuple(key) for key in found["keys"]] == [(code, "pressed"), (code, "released")],
             "a hotkey reached the target as a remote control key: before OK the target got %r" % (found["keys"],))
    return ["Ctrl+Alt+R showed and hid the initially hidden on-screen remote control",
            "Ctrl+Alt+M muted the run's audio process and then unmuted it (asked of the process itself each time)",
            "Ctrl+Alt+1: from a %dx%d window the %dx%d display went back to %dx%d screen pixels"
            % (one["resized"][0], one["resized"][1], width, height, width, height),
            "none of the hotkeys pressed until then (Ctrl+Alt+F, F11, Ctrl+Alt+R, Ctrl+Alt+M, Ctrl+Alt+1) reached "
            "the target: the first key it got was the OK pressed after them"]


def _key_lines(found, how):
    wrong = ["%s (%s)" % (key, "nothing arrived" if not entry["arrived"] else
                          "arrived as %r" % (entry["arrived"],)) for key, entry in found.items() if not entry["ok"]]
    _require(not wrong, "%s, these remote control keys did not reach the target as their own key: %s"
             % (how, ", ".join(wrong)))
    missing = [key for key, _, _, _ in remote.KEYS if key not in found]
    _require(not missing, "%s, there is no way to press: %s" % (how, ", ".join(missing)))
    unnamed = sorted(key for key, entry in found.items() if entry["symbol"] in (None, "", "NoSymbol"))
    lines = ["%s: all %d remote control keys reached a program on the target's display, each pressed and released "
             "with its own Linux key code" % (how, len(found))]
    lines.append("key symbols in the target: " + ", ".join(
        "%s %s" % (key, found[key]["symbol"]) for key in ("up", "ok", "back", "red", "play", "channel_up", "exit")))
    if unnamed:
        lines.append("with a key code but no symbol in the target's keymap: " + ", ".join(unnamed))
    return lines


def _remote_keys(mode, arch="native"):
    """Host keyboard keys are remote control keys while the window has the focus."""
    seen = _window(mode, arch)
    _require(not remote.problems(), "; ".join(remote.problems()))
    lines = _key_lines(seen["host_keys"], "typed into the emulator's window on the host keyboard")
    lines.append("host keys: " + ", ".join("%s for %s" % (entry["host"], remote.LABELS[key])
                                           for key, entry in seen["host_keys"].items()))
    return lines + ["not checked: that the keys stay away from the target while another window has the focus"]


def _remote_window(mode, arch="native"):
    """The on-screen remote control."""
    seen = _window(mode, arch)
    state = seen["remote"]
    _require(not seen["initial_remote_window"], "the on-screen remote control was not hidden when the display opened")
    _require(state["remote_window"], "the on-screen remote control did not open when toggled")
    lines = _key_lines(seen["buttons"], "clicked on the on-screen remote control")
    _require(seen["remote_picture"], "the on-screen remote control did not draw itself")
    _require(seen["key_in_remote"]["ok"], "a host key typed into the remote control's window did not reach the "
             "target: %r" % (seen["key_in_remote"],))
    return ["the remote control starts hidden, opens on demand in its own window (%dx%d), with a button for each of the %d keys"
            % (seen["remote_picture"][0], seen["remote_picture"][1], len(state["remote_buttons"]))] + lines + [
        "with the remote control shown, the host keys still worked in the emulator's window (%d keys) and in the "
        "remote control's own" % len(seen["host_keys"])]


def _settings_fields():
    """The settings window's fields, as the arguments of "emu run" make them."""
    from .cli import run_parser
    merged = {"window", "fullscreen"}
    names = {action.dest for action in run_parser()._actions if action.dest != "help"}
    return sorted((names - merged) | {"window_mode"})


def check_settings_window():
    """The settings window offers every launcher setting and produces the
    arguments for it."""
    from .cli import run_parser
    if not window.gui_python():
        raise CheckUnavailable("Qt for Python (%s) is not installed on this host; %s" % (window.PACKAGE, host.SETUP_HINT))
    chosen = {"mode": "vm", "arch": "arm64", "workload": "graphics-demo", "window_mode": "full screen",
              "resolution": "4k", "graphics": "emulated", "cpus": 2, "memory": 1024,
              "mute": True, "option": "accel=tcg verbose-boot=yes", "driver": "hwrng=mocked", "repeat": 2,
              "timeout": "120", "record": True, "workload_args": "--tests wayland --seconds 1"}
    answer = window.choose_settings(script={"set": chosen, "press": "start"})
    _require(answer.get("visible"), "the settings window was not shown")
    _require(answer["fields"] == _settings_fields(), "the window's fields are not the launcher's arguments: it has %r, "
             "the launcher takes %r" % (answer["fields"], _settings_fields()))
    _require(answer["redrat_profile_ids"] == [None] + [item["id"] for item in redrat.profiles()] and
             answer["redrat_create_button"] == "Create new profile...",
             "profile creation is not a separate action beside the RedRat profile selector")
    _require(answer["arguments"] and answer["arguments"][0] == "run", "Start produced %r" % (answer["arguments"],))
    parsed = run_parser().parse_args(answer["arguments"][1:])
    expected = {"mode": "vm", "arch": "arm64", "workload": "graphics-demo", "fullscreen": True, "window": False,
                "resolution": "4k", "graphics": "emulated", "cpus": 2, "memory": 1024,
                "mute": True, "option": ["accel=tcg", "verbose-boot=yes"], "driver": ["hwrng=mocked"], "repeat": 2,
                "timeout": 120.0, "record": True, "workload_args": ["--", "--tests", "wayland", "--seconds", "1"]}
    wrong = {name: getattr(parsed, name) for name, value in expected.items() if getattr(parsed, name) != value}
    _require(not wrong, "the arguments from the window do not say what was set: %r" % wrong)
    # The command line the window shows is the one of those arguments.
    _require(shlex.split(answer["command"]) == ["emu"] + answer["arguments"],
             "the window shows the command line %r, and Start produced %r" % (answer["command"], answer["arguments"]))
    plain = window.choose_settings(script={"press": "start"})
    _require(plain["arguments"] == ["run"], "with nothing changed, Start produced %r" % (plain["arguments"],))
    _require(plain["command"] == "emu run", "with nothing changed, the window shows the command line %r"
             % (plain["command"],))
    _require(plain["enabled"]["arch"] is False, "the VM guest CPU can be chosen in container mode")
    refused = window.choose_settings(script={"set": {"timeout": "soon"}, "press": "start"})
    _require(refused["arguments"] is None and refused["problem"], "a setting the launcher refuses was accepted")
    closed = window.choose_settings(script={"press": "close"})
    _require(closed["arguments"] is None, "closing the window produced %r" % (closed["arguments"],))
    return ["the window has a field for every argument of \"emu run\": %s" % ", ".join(answer["fields"]),
            "mode, VM guest CPU (off in container mode), workload, window mode and the others set as a person "
            "would; Start gave: %s" % answer["command"],
            "the launcher's own parser reads those arguments as what was set, and the command line the window "
            "shows is the one of those arguments; with nothing set it shows \"emu run\"",
            "unchanged, Start gives \"emu run\"; a timeout of \"soon\" is refused with the launcher's reason (%s); "
            "closing the window starts nothing" % refused["problem"]]


def check_redrat_support():
    python = window.gui_python()
    if not python:
        raise CheckUnavailable("RedRat GUI checks need Qt for Python; " + host.SETUP_HINT)
    if not redrat.installed():
        raise CheckUnavailable("RedRat SDK bridge missing or out of date; " + host.SETUP_HINT)
    done = subprocess.run([python, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-p", "test_redrat*.py"],
                          capture_output=True, text=True, timeout=120,
                          env=host.tool_env({"QT_QPA_PLATFORM": "offscreen"}), cwd=ROOT)
    _require(done.returncode == 0, "RedRat automated checks failed:\n" + done.stdout + done.stderr)
    sdk = subprocess.run(redrat.command("self-test"), capture_output=True, text=True, timeout=30,
                         env=redrat.environment())
    _require(sdk.returncode == 0, "RedRat SDK matching checks failed:\n" + sdk.stdout + sdk.stderr)
    return [done.stderr.strip(), sdk.stdout.strip(),
            "software checks only: SDK signal matching, profiles, guided learning, detection gating, all 32 key codes, "
            "IR holds and focus release; not a physical infrared result"]


def check_redrat_device():
    if not redrat.installed():
        raise CheckUnavailable("RedRat SDK bridge missing or out of date; " + host.SETUP_HINT)
    found = redrat.devices()
    if not found:
        raise CheckUnavailable("no RedRat receiver detected")
    if len(found) != 1:
        raise CheckUnavailable("this automatic check needs exactly one attached RedRat receiver")
    try:
        process = subprocess.Popen(redrat.command("listen", "--device", found[0]["id"]), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=redrat.environment())
    except OSError as error:
        raise CheckFailed("cannot start RedRat receiver: %s" % error) from error
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
    try:
        try:
            line = lines.get(timeout=20)
        except queue.Empty:
            raise CheckFailed("RedRat receiver did not report ready within 20 seconds")
        try:
            ready = json.loads(line)
        except ValueError:
            raise CheckFailed("RedRat receiver did not return a ready event: %r" % line)
        _require(ready.get("event") == "ready", "RedRat receiver's first event was not ready: %r" % ready)
        process.stdin.write('{"do":"quit"}\n')
        process.stdin.flush()
        try:
            _, errors = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            raise CheckFailed("RedRat receiver did not close within 10 seconds")
        _require(process.returncode == 0, "RedRat receiver failed to shut down: %s" % errors)
        return ["the SDK detected and opened %s; the receiver reported ready and shut down cleanly" % found[0]["name"],
                "IR key delivery remains unverified until a real remote is learned and its buttons are pressed"]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def check_settings_launch():
    """Started without arguments, the launcher shows the settings window, and
    starting from it runs what the same arguments run."""
    if not window.gui_python():
        raise CheckUnavailable("Qt for Python (%s) is not installed on this host; %s" % (window.PACKAGE, host.SETUP_HINT))
    arguments = ["run", "--workload", "driver-check", "--driver", "hwrng=mocked"]
    script = {"set": {"workload": "driver-check", "driver": "hwrng=mocked"}, "press": "start"}
    launcher = [sys.executable, "-m", "emulator"]
    environment = host.tool_env({"PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"})

    def results_of(command, extra=None):
        done = subprocess.run(command, capture_output=True, text=True, timeout=900, cwd=str(ROOT),
                              env=dict(environment, **(extra or {})), stdin=subprocess.DEVNULL)
        found = [json.loads(line.split("EMU-RESULT: ", 1)[1]) for line in done.stdout.splitlines()
                 if "EMU-RESULT: " in line]
        return done, [(item.get("feature"), item.get("strategy"), item.get("provider"), item.get("sample_hex"),
                       item.get("ok")) for item in found]

    from_window, shown = results_of(launcher, {cli_settings_variable(): json.dumps(script)})
    _require(from_window.returncode == 0, "started without arguments, the launcher ended with status %d: %s"
             % (from_window.returncode, from_window.stderr.strip()[-300:]))
    said = [line for line in from_window.stderr.splitlines() if line.startswith("emu: emu run")]
    _require(said == ["emu: emu " + " ".join(arguments)], "the launcher did not start what the window gave it: %r"
             % (said or from_window.stderr.strip()[-200:],))
    direct, plain = results_of(launcher + arguments)
    _require(direct.returncode == 0, "the same arguments on the command line ended with status %d" % direct.returncode)
    _require(shown and shown == plain, "from the window the workload reported %r, from the command line %r"
             % (shown, plain))
    with_arguments, _ = results_of(launcher + ["workloads"], {cli_settings_variable(): json.dumps({"press": "close"})})
    _require("remote-keys" in with_arguments.stdout, "with arguments the launcher did not do as they say")
    return ["\"emu\" without arguments showed the settings window; the driver check was chosen in it and started, "
            "and the launcher ran: %s" % said[0][5:],
            "its results are those of the same arguments on the command line: %r" % (shown,),
            "with arguments (\"emu workloads\") the launcher did as they say, without the window"]


def cli_settings_variable():
    from .cli import SETTINGS_SCRIPT_VARIABLE
    return SETTINGS_SCRIPT_VARIABLE


def _window_checks():
    variants = (("container", "container", "native", "container mode"),
                ("vm", "vm", "native", "a host-native VM"),
                ("vm-arm64", "vm", "arm64", "an ARM64 VM"),
                ("vm-arm32", "vm", "arm32", "an ARM32 VM"))
    checks = {}
    for suffix, mode, arch, where in variants:
        checks["window-display-" + suffix] = (lambda m=mode, a=arch: _window_display(m, a), "7.1",
                                              "the launcher's window shows the display of " + where)
        checks["window-fullscreen-" + suffix] = (lambda m=mode, a=arch: _window_fullscreen(m, a), "7.1",
                                                 "the hotkey switches to full screen and back, with " + where)
    for suffix, mode, arch, where in variants:
        checks["window-scaling-" + suffix] = (lambda m=mode, a=arch: _window_scaling(m, a), "7.2",
                                              "the display scales with the window, with " + where)
        checks["window-toolbar-" + suffix] = (lambda m=mode, a=arch: _window_toolbar(m, a), "7.2",
                                              "the toolbar's 1:1 and mute buttons work, with " + where)
    for suffix, mode, arch, where in variants:
        checks["window-buttons-" + suffix] = (lambda m=mode, a=arch: _window_buttons(m, a), "9.2",
                                              "the toolbar's full screen and remote control buttons work, with "
                                              + where)
        checks["window-hotkeys-" + suffix] = (lambda m=mode, a=arch: _window_hotkeys(m, a), "9.2",
                                              "the hotkeys for mute, 1:1 and the remote control work, with " + where)
    checks["settings-window"] = (check_settings_window, "7.3, 9.2",
                                 "the settings window offers every launcher setting and gives its arguments and "
                                 "their command line")
    checks["settings-launch"] = (check_settings_launch, "7.3",
                                 "without arguments the launcher shows the settings window and starts from it")
    for suffix, mode, arch, where in variants:
        checks["remote-keys-" + suffix] = (lambda m=mode, a=arch: _remote_keys(m, a), "7.4",
                                           "host keyboard keys reach the target as remote control keys in " + where)
    for suffix, mode, arch, where in variants:
        checks["remote-window-" + suffix] = (lambda m=mode, a=arch: _remote_window(m, a), "7.5",
                                             "the on-screen remote control's buttons reach the target in " + where)
    return checks


# ---------------------------------------------------------- STB simulator ---

# The colours of the user interface (target/rootfs/opt/emu/stb/stb.css): the
# page, and the item that is selected.
STB_PAGE_COLOR = (13, 17, 23)
STB_FOCUS_COLOR = (61, 139, 253)
# The block at the top centre of the video on demand test title names the
# representation that is shown (target/media/build-abr.sh).
ABR_MARKERS = {"0": (255, 224, 0), "1": (0, 224, 160), "2": (255, 64, 160)}
# The tone of each channel's audio codec (target/media/build-media.sh).
CHANNEL_TONES = {1: ("mp2", 440), 2: ("aac", 880), 3: ("ac3", 660)}
STB_HOW = {"host": "typed on the host keyboard", "click": "clicked on the on-screen remote control"}
_stb_runs = {}


class _Stb:
    """One run of the STB simulator, operated as a person would: with remote
    control keys, typed into the emulator's window on the host keyboard or
    clicked on the on-screen remote control. What the user interface does is
    read from the EMU-STB lines the workload prints."""

    def __init__(self, viewer, seen, width, height, directory, slow):
        self.viewer = viewer
        self.seen = seen
        self.width, self.height = width, height
        self.directory = directory
        self.patience = 1800 if slow else 240       # seconds to wait for a slow thing: a page, a stream
        self.shots = 0

    # ------------------------------------------------------------ events ---

    def mark(self):
        with self.seen["lock"]:
            return len(self.seen["events"])

    def wait(self, start, wanted, seconds=None):
        """The first event since `start` that `wanted` accepts, or None."""
        def found():
            with self.seen["lock"]:
                events = self.seen["events"][start:]
            return next((event for event in events if wanted(event)), None)
        return _wait(found, self.patience if seconds is None else seconds, 0.1)

    def last(self, wanted):
        with self.seen["lock"]:
            return next((event for event in reversed(self.seen["events"]) if wanted(event)), None)

    # -------------------------------------------------------------- keys ---

    def press(self, key, how="host"):
        if how == "click":
            answer = self.viewer.ask(do="remote-click", key=key)
        else:
            answer = self.viewer.ask(do="host-key", key=remote.host_keys_of(key)[0])
        if "error" in answer:
            raise CheckFailed("the window did not take the %s key: %s" % (remote.LABELS[key], answer["error"]))

    def press_for(self, key, wanted, what, how="host", seconds=None):
        """Press a key and wait for what it should bring about."""
        start = self.mark()
        self.press(key, how)
        event = self.wait(start, wanted, seconds)
        if event is None:
            raise CheckFailed("after %s (%s), %s did not happen; the user interface last reported: %r"
                              % (remote.LABELS[key], STB_HOW[how], what, self.last(lambda event: True)))
        return event

    def screen(self, name):
        return lambda event: event.get("event") == "screen" and event.get("screen") == name

    def awake(self, how="host"):
        """Wait until the user interface takes keys. A browser that has just
        started shows its page a moment before it has the keyboard; the red
        key has no function in the user interface, which reports such a key."""
        for _ in range(60):
            start = self.mark()
            self.press("red", how)
            if self.wait(start, lambda event: event.get("event") == "key", 3 if self.patience < 1000 else 20):
                return
        raise CheckFailed("the user interface takes no keys: none of 60 presses of the red key was reported")

    def to_home(self, how="host"):
        """EXIT goes home from anywhere. Right after the user interface has
        appeared the browser may not have the keyboard yet, so a key that
        brings nothing about is pressed again."""
        for _ in range(5):
            start = self.mark()
            self.press("exit", how)
            event = self.wait(start, self.screen("home"), 10 if self.patience < 1000 else 60)
            if event is not None:
                return event
        return self.press_for("exit", self.screen("home"), "the home screen", how)

    def select(self, shown, target, how="host"):
        """Move the selection of a list to `target` with Up and Down. `shown`
        is the event that listed it: its items, and which one is selected."""
        items, focus = shown["items"], shown["focus"]
        if target not in items:
            raise CheckFailed("the %s screen does not list %r (it lists: %s)" % (shown["screen"], target,
                                                                              ", ".join(items)))
        steps = items.index(target) - items.index(focus)
        for _ in range(abs(steps)):
            focus = items[items.index(focus) + (1 if steps > 0 else -1)]
            self.press_for("down" if steps > 0 else "up",
                           lambda event, focus=focus: event.get("event") == "focus" and event.get("focus") == focus,
                           "the selection moving to %r" % focus, how)

    def open(self, shown, target, opens, how="host"):
        """Select an item of a list and press OK; returns the screen event."""
        self.select(shown, target, how)
        return self.press_for("ok", self.screen(opens), "the %s screen" % opens, how)

    # ---------------------------------------------------------- pictures ---

    def picture(self):
        self.shots += 1
        path = os.path.join(self.directory, "stb-%d.ppm" % self.shots)
        # The window connects to the display on its own, and in container mode
        # keys reach the target another way: the user interface can report a
        # key before the window has the display's first picture. Wait for it.
        saved = _wait(lambda: (lambda answer: answer if answer.get("saved") else None)(
            self.viewer.ask(do="save-display", path=path)), 30 if self.patience < 1000 else 180, 0.1)
        if not saved:
            raise CheckFailed("the window could not save the display's picture: %r"
                              % self.viewer.ask(do="save-display", path=path))
        return path

    def video_problems(self, marker):
        """What is wrong with the display as a picture of a full-screen video
        with the reference streams' marker blocks and this one at the top."""
        path = self.picture()
        found = imagefile.size(path)
        entry = {"file": path, "captured_width": found[0], "captured_height": found[1], "marker": tuple(marker)}
        return graphics.capture_problems(entry, self.width, self.height, tolerance=graphics.VIDEO_COLOR_TOLERANCE)

    def interface_problems(self):
        """What is wrong with the display as a picture of the user interface:
        its page colour at the edge, and a selected item."""
        path = self.picture()
        image = imagefile.load(path)
        if (image.width, image.height) != (self.width, self.height):
            return ["the display's picture is %dx%d, not %dx%d" % (image.width, image.height, self.width, self.height)]
        close = lambda a, b: all(abs(x - y) <= 24 for x, y in zip(a, b))
        problems = []
        edge = image.pixel(self.width // 100, self.height // 2)
        if not close(edge, STB_PAGE_COLOR):
            problems.append("the left edge is %s, not the page's %s" % (edge, STB_PAGE_COLOR))
        step = max(1, self.height // 90)
        selected = sum(1 for y in range(0, self.height, step) for x in range(0, self.width, step)
                       if close(image.pixel(x, y), STB_FOCUS_COLOR))
        if selected < 40:
            problems.append("no selected item is to be seen (%d sample points have its colour)" % selected)
        return problems

    # ---------------------------------------------------------- the tour ---

    def tour(self, how):
        """7.7: every part of the user interface, with keys alone."""
        steps = []
        self.awake(how)
        home = self.to_home(how)
        steps.append("EXIT: the home screen, listing %s" % ", ".join(home["items"]))
        if how == "host":
            problems = _wait(lambda: self.interface_problems() == [] or None, 30, 1.0)
            _require(problems, "the display does not show the user interface: %s" % "; ".join(self.interface_problems()))
            steps.append("a capture of the display shows the user interface: its page and a selected item")
        for target, opens in (("channels", "channels"), ("apps", "apps"), ("performance", "performance")):
            home = self.last(self.screen("home"))
            home = dict(home, focus=(self.last(lambda e: e.get("event") in ("focus", "screen")
                                               and e.get("screen") == "home") or home)["focus"])
            shown = self.open(home, target, opens, how)
            steps.append("Up/Down to %r and OK: the %s screen, listing %s" % (target, opens,
                                                                             ", ".join(shown["items"]) or "nothing"))
            self.press_for("back", self.screen("home"), "the home screen again", how)
        steps.append("BACK returned to the home screen each time")
        return steps

    def home_now(self):
        """The home screen as it is: its items, and the selection."""
        home = self.last(self.screen("home"))
        moved = self.last(lambda e: e.get("event") in ("focus", "screen") and e.get("screen") == "home")
        return dict(home, focus=(moved or home)["focus"])

    # ---------------------------------------------------------- channels ---

    def channels(self):
        """7.8: the channel list, a channel, another channel."""
        found = {"played": []}
        self.to_home()
        listed = self.open(self.home_now(), "channels", "channels")
        found["listed"] = listed["items"]
        playing = lambda number: (lambda event: event.get("event") == "channel" and event.get("number") == number
                                  and event.get("state") in ("playing", "error"))

        def played(number, event, how):
            if event["state"] != "playing":
                raise CheckFailed("channel %d was not played: %s" % (number, event.get("reason")))
            marker = next(c["marker"] for c in self.seen["described"]["channels"] if c["number"] == number)
            time.sleep(1.0)
            problems = _wait(lambda: self.video_problems(marker) == [] or None, 60, 1.0)
            found["played"].append({"number": number, "how": how, "video": event.get("video"),
                                    "sound": event.get("sound"), "at": time.time(),
                                    "problems": [] if problems else self.video_problems(marker)})
            time.sleep(4.0)         # its sound, for the recording on the host

        self.select(listed, "2")
        played(2, self.press_for("ok", playing(2), "channel 2 playing"), "selected in the channel list")
        played(3, self.press_for("up", playing(3), "channel 3 playing"), "Up while channel 2 played")
        played(1, self.press_for("1", playing(1), "channel 1 playing"), "the digit 1 while channel 3 played")
        self.press_for("back", self.screen("channels"), "the channel list again")
        found["ended"] = time.time()
        return found

    # --------------------------------------------------------------- vod ---

    def vod(self):
        """7.9: the app launcher, the video on demand application, an ABR
        title, and back."""
        found = {}
        self.to_home()
        apps = self.open(self.home_now(), "apps", "apps")
        found["apps"] = apps["items"]
        _require("vod" in apps["items"], "the app launcher does not list the video on demand application")
        self.select(apps, "vod")
        titles_shown = lambda event: event.get("event") == "vod" and event.get("state") == "titles"
        titles = self.press_for("ok", titles_shown, "the video on demand application showing its titles")
        found["titles"] = titles["titles"]
        found["dash_js"] = (self.last(lambda e: e.get("event") == "vod" and e.get("state") == "ready") or {}).get("dash_js")

        def choose(title):
            shown = self.last(titles_shown)
            items, focus = shown["titles"], shown["focus"]
            steps = items.index(title) - items.index(focus)
            for _ in range(abs(steps)):
                focus = items[items.index(focus) + (1 if steps > 0 else -1)]
                self.press_for("down" if steps > 0 else "up",
                               lambda event, focus=focus: titles_shown(event) and event.get("focus") == focus,
                               "the selection moving to %r" % focus)

        def play(title, enough):
            """Play a title until `enough` says so of its events; returns them."""
            choose(title)
            start = self.mark()
            self.press("ok")
            mine = lambda event: event.get("event") == "vod" and event.get("title") == title

            def events():
                with self.seen["lock"]:
                    return [event for event in self.seen["events"][start:] if mine(event)]
            _wait(lambda: enough(events()) or any(e["state"] == "error" for e in events()) or None, self.patience, 0.2)
            return events()

        def test_title(title, wanted):
            happened = play(title, lambda events: wanted(events) and any(
                e["state"] == "progress" and e.get("time", 0) >= 3 for e in events))
            errors = [e.get("reason") for e in happened if e["state"] == "error"]
            _require(not errors, "%s was not played: %s" % (title, errors))
            if not any(e["state"] == "progress" and e.get("time", 0) >= 3 for e in happened):
                with self.seen["lock"]:
                    recent = [{k: v for k, v in e.items() if k not in ("representations", "titles", "user_agent")}
                              for e in self.seen["events"][-12:]]
                raise CheckFailed("%s did not play for three seconds; the last things reported: %r" % (title, recent))
            representations = [e["representation"] for e in happened if e["state"] == "representation"]
            stream = next((e for e in happened if e["state"] == "stream"), {})
            # The picture names the representation that is shown; it may change
            # between a look at the events and the capture.
            problems = None
            for _ in range(8):
                shown = self.last(lambda e: e.get("event") == "vod" and e.get("state") == "representation")
                marker = ABR_MARKERS.get(str(shown["representation"]["id"]))
                problems = self.video_problems(marker) if marker else ["no marker for representation %r" % shown]
                if not problems:
                    break
                time.sleep(1.0)
            self.press_for("back", titles_shown, "the titles again")
            return {"title": title, "representations": representations, "offered": stream.get("representations") or [],
                    "shown": shown["representation"], "problems": problems}

        only_smallest = lambda events: any(e["state"] == "representation" for e in events)
        found["slow"] = test_title("test-pattern-slow", only_smallest)
        found["fast"] = test_title("test-pattern", lambda events: any(
            e["state"] == "representation" and str(e["representation"]["id"]) != "0" for e in events))

        # A film on the internet: played where the target reaches it, and
        # refused with a message where it does not.
        film = "big-buck-bunny"
        happened = play(film, lambda events: any(e["state"] == "progress" and e.get("time", 0) >= 3 for e in events))
        error = next((e for e in happened if e["state"] == "error"), None)
        progress = [e for e in happened if e["state"] == "progress"]
        found["film"] = {"title": film, "error": error and error.get("reason"), "played": bool(progress) and not error,
                         "representations": [e["representation"] for e in happened if e["state"] == "representation"],
                         "offered": len((next((e for e in happened if e["state"] == "stream"), {})).get("representations") or []),
                         "seconds": progress[-1].get("time") if progress else 0}
        if error:
            self.press("ok")        # the message goes; the titles are underneath
            choose("elephants-dream")
            found["film"]["usable_after_error"] = True
        elif progress:
            self.press_for("back", titles_shown, "the titles again")
        else:
            raise CheckFailed("%s neither played nor was refused: %r" % (film, happened[-3:]))
        back = self.press_for("back", self.screen("apps"), "the simulator's app launcher again")
        found["returned"] = back["screen"]
        return found

    # --------------------------------------------------------- workloads ---

    def workloads(self):
        """7.10: each performance workload, started from the user interface."""
        found = {"runs": []}
        self.to_home()
        listed = self.open(self.home_now(), "performance", "performance")
        found["listed"] = listed["items"]
        for name in listed["items"]:
            shown = self.last(self.screen("performance"))
            moved = self.last(lambda e: e.get("event") in ("focus", "screen") and e.get("screen") == "performance")
            self.select(dict(shown, focus=(moved or shown)["focus"]), name)
            start = self.mark()
            self.press("ok")
            finished = self.wait(start, lambda event: event.get("event") == "workload" and event.get("id") == name
                                 and event.get("state") == "finished", 4 * self.patience)
            if finished is None:
                raise CheckFailed("the %s workload, started from the user interface, did not finish" % name)
            results = self.wait(start, self.screen("results"))
            found["runs"].append(dict(finished, results_screen=bool(results)))
            if results is None:
                raise CheckFailed("after the %s workload the user interface did not show its results" % name)
            self.awake()            # the browser was started again after a workload that took the display
            self.press_for("back", self.screen("performance"), "the list of performance tests again")
        return found

    def off(self):
        self.to_home()
        self.select(self.home_now(), "off")
        self.press("ok")


def _stb_session(mode, arch):
    """One run of the STB simulator per mode, with everything the checks look
    at done in it. Returns what was observed."""
    key = (mode, arch)
    if key in _stb_runs:
        return _stb_runs[key]
    if not window.gui_python():
        raise CheckUnavailable("Qt for Python (%s) is not installed on this host, so the launcher has no windows; %s"
                               % (window.PACKAGE, host.SETUP_HINT))
    width, height = graphics.resolution(WINDOW_RESOLUTION)
    seen = {"events": [], "lock": threading.Lock(), "ready": threading.Event(), "described": None, "parts": {}}

    def on_line(line):
        for marker in ("EMU-STB: ", "EMU-WORKLOAD: "):
            start = line.find(marker)
            if start < 0:
                continue
            try:
                data = json.loads(line[start + len(marker):])
            except ValueError:
                return
            if marker == "EMU-WORKLOAD: ":
                if data.get("id") == "stb-simulator":
                    seen["described"] = data
                return
            with seen["lock"]:
                seen["events"].append(data)
            if data.get("event") == "screen" and data.get("screen") == "home":
                seen["ready"].set()

    sink = _HostSink()
    with tempfile.TemporaryDirectory(prefix="emu-verify-") as directory:
        def drive(viewer):
            def work():
                stb = _Stb(viewer, seen, width, height, directory, slow=arch != "native")
                try:
                    if not seen["ready"].wait(3600):
                        seen["error"] = "the user interface never appeared: no home screen was reported"
                        return
                    seen["started"] = time.time()
                    for name, part in (("tour-host", lambda: stb.tour("host")), ("tour-click", lambda: stb.tour("click")),
                                       ("channels", stb.channels), ("vod", stb.vod), ("workloads", stb.workloads)):
                        try:
                            seen["parts"][name] = part()
                        except CheckFailed as error:
                            seen["parts"][name] = {"error": str(error)}
                        except Exception as error:      # reported by the check of that part
                            seen["parts"][name] = {"error": "%s: %s" % (type(error).__name__, error)}
                    stb.off()
                except Exception as error:
                    seen["error"] = "%s: %s" % (type(error).__name__, error)
                    try:
                        viewer.ask(do="quit")           # closing the window ends the emulator
                    except (EmuError, OSError, ValueError):
                        pass
            threading.Thread(target=work, daemon=True).start()

        try:
            _, outcome = _run(mode=mode, arch=arch, workload="stb-simulator", args=["--quick"],
                              resolution=WINDOW_RESOLUTION, window=True,
                              drivers=driver_features.parse(["audio=host"]), options=sink.options(),
                              on_line=on_line, on_audio=sink.watch, on_viewer=drive, timeout=4 * 3600)
        finally:
            seen["heard"] = sink.close()
    seen["sink"] = sink
    seen["trace"] = _trace(outcome)
    seen["results"] = outcome.results
    seen["emulator"] = outcome.environment["emulator"]
    _stb_runs[key] = seen
    return seen


def _stb_part(mode, arch, name):
    seen = _stb_session(mode, arch)
    _require("error" not in seen or name in seen["parts"], seen.get("error"))
    part = seen["parts"].get(name)
    _require(part is not None, "this part of the run was not reached: %s" % seen.get("error"))
    _require(not (isinstance(part, dict) and "error" in part), isinstance(part, dict) and part.get("error"))
    return seen, part


def _stb_start(mode, arch="native"):
    """The simulator starts, shows its user interface, and every part of it
    is reached with remote control keys from the keyboard and the on-screen
    remote control."""
    seen, by_keyboard = _stb_part(mode, arch, "tour-host")
    _, by_clicks = _stb_part(mode, arch, "tour-click")
    described = seen["described"] or {}
    lines = ["the stb-simulator workload %s started: %s at %s, with %d channels, %d titles and the performance "
             "workloads %s" % (described.get("version"), described.get("browser"), described.get("resolution"),
                               len(described.get("channels") or []), len(described.get("titles") or []),
                               ", ".join(described.get("workloads") or []))]
    lines += ["%s: %s" % (STB_HOW["host"], step) for step in by_keyboard]
    lines.append("%s: the same tour, with the same screens (%d steps)" % (STB_HOW["click"], len(by_clicks)))
    lines.append("not covered: physical RedRat IR input; use redrat-device for receiver readiness and learn a real remote")
    return lines + ["graphics provider: %s" % seen["emulator"]["graphics"]["provider"]]


def _stb_channels(mode, arch="native"):
    """The channel list plays the selected channel, and another one after it."""
    seen, found = _stb_part(mode, arch, "channels")
    _require(len(found["listed"]) >= 3, "the channel list has %d channels" % len(found["listed"]))
    lines = ["the channel list has the channels %s" % ", ".join(found["listed"])]
    for played in found["played"]:
        _require(not played["problems"], "channel %d (%s) is not what the display shows: %s"
                 % (played["number"], played["how"], "; ".join(played["problems"])))
        lines.append("channel %d, %s: playing at %s; a capture of the display shows its video" % (
            played["number"], played["how"], played["video"]))
    # The sound: each channel's tone, in the order the channels were played.
    received = [(row["level"], row["hz"]) for row in seen["trace"]]
    sink = seen["sink"]
    heard = seen["heard"] if sink.name else None
    for windows, where in ((received, "the host-side audio process"), (heard, sink.where)):
        if windows is None:
            continue
        first = {}
        for played in found["played"]:
            codec, hz = CHANNEL_TONES[played["number"]]
            at = [index for index, (level, pitch) in enumerate(windows) if level >= LOUD and abs(pitch - hz) <= hz * 0.05]
            _require(len(at) >= 5, "the %d Hz tone of channel %d (%s) did not reach %s"
                     % (hz, played["number"], AUDIO_CODECS[codec], where))
            first[played["number"]] = at[0]
        order = [played["number"] for played in found["played"]]
        _require(sorted(order, key=lambda number: first[number]) == order,
                 "at %s the channels' tones came in another order than the channels were played" % where)
        lines.append("at %s: the tones of the channels in the order they were played (%s)" % (
            where, ", ".join("%d Hz for channel %d" % (CHANNEL_TONES[n][1], n) for n in order)))
    if not sink.name:
        lines.append("not recorded at the host's output: %s" % sink.reason)
    return lines + sink.evidence()


def _stb_vod(mode, arch="native"):
    """The video on demand application starts from the app launcher, plays
    adaptive bitrate titles with dash.js, and returns to the simulator."""
    seen, found = _stb_part(mode, arch, "vod")
    for film in ("big-buck-bunny", "elephants-dream"):
        _require(film in found["titles"], "the video on demand application does not offer %s" % film)
    _require(found["dash_js"], "the video on demand application did not load dash.js")
    lines = ["the app launcher lists %s; OK started the video on demand application in the browser, with dash.js %s"
             % (", ".join(found["apps"]), found["dash_js"]),
             "its titles: %s" % ", ".join(found["titles"])]
    slow, fast = found["slow"], found["fast"]
    for played in (slow, fast):
        _require(not played["problems"], "%s is not what the display shows: %s" % (played["title"],
                                                                                   "; ".join(played["problems"])))
    size = lambda r: "%sx%s at %.2f Mbit/s" % (r.get("width"), r.get("height"), (r.get("bandwidth") or 0) / 1e6)
    _require(len(fast["offered"]) >= 3, "the test title offers %d representations" % len(fast["offered"]))
    _require({str(r["id"]) for r in slow["representations"]} == {"0"},
             "over the slow connection the player showed more than the smallest representation: %s"
             % ", ".join(size(r) for r in slow["representations"]))
    _require(str(fast["shown"]["id"]) != "0", "the player stayed at the smallest representation")
    lines.append("the test title is an MPEG-DASH stream with %d video representations (%s)" % (
        len(fast["offered"]), ", ".join(size(r) for r in fast["offered"])))
    lines.append("over a connection of 0.6 Mbit/s the player showed %s only; a capture of the display shows that "
                 "representation's picture" % size(slow["shown"]))
    lines.append("without the limit it went from %s to %s; a capture shows that one" % (
        size(fast["representations"][0]), size(fast["shown"])))
    film = found["film"]
    if film["played"]:
        lines.append("from the internet, %s played for %.0f s: %d representations offered, shown at %s" % (
            film["title"], film["seconds"], film["offered"],
            ", then ".join(size(r) for r in film["representations"]) or "an unnamed one"))
    else:
        _require(film.get("usable_after_error"), "after a title that could not be played the application was stuck")
        lines.append("from the internet, %s could not be played here (%s); the application said so and stayed usable"
                     % (film["title"], film["error"]))
    lines.append("BACK at the titles left the application: the simulator's %s screen was shown again" % found["returned"])
    return lines + ["not played here: Elephants Dream, Sintel and Tears of Steel, which are offered the same way"]


def _stb_workloads(mode, arch="native"):
    """Each performance workload starts from the user interface, runs and
    reports its results."""
    seen, found = _stb_part(mode, arch, "workloads")
    wanted = sorted(w["id"] for w in catalog.workloads()["workloads"] if w.get("kind") == "performance"
                    and w.get("status") == "implemented")
    _require(sorted(found["listed"]) == wanted, "the user interface offers %s, and the performance workloads are %s"
             % (", ".join(found["listed"]), ", ".join(wanted)))
    lines = ["the user interface offers every performance workload: %s" % ", ".join(found["listed"])]
    for run in found["runs"]:
        reported = [r for r in seen["results"] if r.get("launched_from") == "stb-simulator"
                    and r.get("workload") == run["id"]]
        measured = [r for r in reported if r.get("value") is not None]
        _require(run["status"] == 0, "%s ended with status %s" % (run["id"], run["status"]))
        _require(measured, "%s reported no measurement to the launcher (%d results, none with a value)"
                 % (run["id"], len(reported)))
        lines.append("%s: ran for %.0f s and reported %d results to the launcher, %d of them measurements (%s); the "
                     "user interface then showed its results" % (
                         run["id"], run["seconds"], len(reported), len(measured),
                         ", ".join(sorted({r["test"] for r in measured}))[:160]))
    return lines + ["these were short runs (--quick): they show that each workload runs and reports, and are not "
                    "measurements to compare"]


def _stb_checks():
    variants = (("container", "container", "native", "container mode"),
                ("vm", "vm", "native", "a host-native VM"),
                ("vm-arm64", "vm", "arm64", "an ARM64 VM"),
                ("vm-arm32", "vm", "arm32", "an ARM32 VM"))
    checks = {}
    for name, function, task, what in (
            ("stb-start", _stb_start, "7.7", "the STB simulator starts and is operated with remote control keys in "),
            ("stb-channels", _stb_channels, "7.8", "the STB simulator plays the selected channel, and another, in "),
            ("stb-vod", _stb_vod, "7.9", "the VOD application plays an ABR title and returns to the simulator in "),
            ("stb-workloads", _stb_workloads, "7.10", "the performance workloads run from the STB simulator in ")):
        for suffix, mode, arch, where in variants:
            checks["%s-%s" % (name, suffix)] = (lambda f=function, m=mode, a=arch: f(m, a), task, what + where)
    return checks


# ------------------------------------------- the launcher's other commands ---

def check_doctor():
    """The command that shows what the launcher finds on the host."""
    from .cli import cmd_doctor
    # With the container image built, the command has graphics in container
    # mode to say something about.
    runtime = container.detect()
    image.ensure("container", lambda: runtime, host.host_arch(), quiet=True)

    def doctor():
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            status = cmd_doctor(None)
        return status, [line for line in said.getvalue().splitlines() if line.strip()]

    status, lines = doctor()
    kinds = {line.split()[0] for line in lines}
    absent = [kind for kind in ("host", "audio", "qemu", "accelerator", "container", "graphics", "windows", "image")
              if kind not in kinds]
    _require(not absent, "the command says nothing about: %s" % ", ".join(absent))
    for mode in ("VM mode", "container mode"):
        _require(any(line.startswith("graphics") and mode + ":" in line and
                     ("host acceleration available: " in line or "emulated only: " in line) for line in lines),
                 "the command does not say whether host graphics acceleration is available in %s, and why" % mode)
    states = [line.split()[-1] for line in lines if line.startswith("image")]
    _require(states and all(state in ("built", "current", "date") for state in states),
             "the command does not say the state of each target image: %r" % (states,))
    missing = [line for line in lines if "MISSING" in line]
    _require((status != 0) == bool(missing), "the command ended with status %d and named %d missing dependencies"
             % (status, len(missing)))
    _require(not missing or host.SETUP_HINT in lines, "with a dependency missing the command does not point to the "
             "setup script")
    targets = [line for line in lines if line.startswith("arm target")]
    _require(len(targets) == len(armtargets.ARCHS) and all(": set up" in line or ": not set up: " in line
                                                           for line in targets),
             "the command does not say for each simulated ARM target whether it is set up: %r" % (targets,))

    def without(hidden):
        """The command once more, with one program hidden from the launcher:
        a stand-in for a host that does not have it."""
        find = host.find_tool
        host.find_tool = lambda name: None if name == hidden else find(name)
        try:
            return doctor()
        finally:
            host.find_tool = find

    # A dependency that is not there: the emulator for the host's own CPU.
    native = vm.QEMU_BINARY[host.host_arch()]
    native_status, native_lines = without(native)
    _require(native_status != 0, "with %s hidden from it, the command reported success" % native)
    _require(any("MISSING " + native in line for line in native_lines), "with %s hidden from it, the command did not "
             "name it as missing" % native)
    _require(host.SETUP_HINT in native_lines, "with %s hidden from it, the command did not point to the setup "
             "script" % native)
    # What only a simulated ARM target needs is no dependency: without the
    # ARM32 emulator the command says that the target is not set up, names
    # the setup option, and ends as it did with it.
    arm = vm.QEMU_BINARY["arm32"]
    arm_status, arm_lines = without(arm)
    _require(not any("MISSING " + arm in line for line in arm_lines), "with %s hidden from it, the command named it "
             "as a missing dependency" % arm)
    _require(any(line.startswith("arm target") and "ARM32: not set up" in line and host.ARM_SETUP_HINT in line
                 for line in arm_lines),
             "with %s hidden from it, the command did not say that the ARM32 target is not set up, with the setup "
             "option" % arm)
    _require(arm_status == status, "with %s hidden from it, the command ended with status %d, not %d as with it"
             % (arm, arm_status, status))
    return ["the command shows the host, the VM emulators, the accelerator, the container runtime, the sound "
            "output, the windows, graphics acceleration in VM and in container mode with the reason, and the state "
            "of %d target images" % len(states),
            "it ended with status %d and named %d missing dependencies; of the simulated ARM targets it says: %s"
            % (status, len(missing), "; ".join(line.split(None, 2)[2] for line in targets)),
            "with %s hidden from the launcher (a stand-in for a host without it) it named that as missing, "
            "pointed to the setup script and ended with status %d" % (native, native_status),
            "with %s hidden, it said that the ARM32 target is not set up and named the setup option, named no "
            "missing dependency for it, and ended with status %d as before" % (arm, arm_status)]


class _ResultsServer:
    """The launcher's results server, started as the report command starts
    it, without a browser and on a port of its own."""

    def __enter__(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.address = "http://127.0.0.1:%d/" % self.port
        self.process = subprocess.Popen(
            [sys.executable, "-m", "emulator", "report", "--no-browser", "--port", str(self.port)], cwd=str(ROOT),
            env=host.tool_env({"PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        said = self.process.stdout.readline()
        if self.address not in said:
            self.__exit__()
            raise CheckFailed("the results command did not start to serve the page: %s"
                              % (said.strip() or "it said nothing"))
        return self

    def __exit__(self, *_):
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process.stdout.close()


def _own_address():
    """An address of this host that other machines reach it at, if it has
    one. No packet is sent: the system only names the address it would use."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") else address


def check_report_serve():
    """The results command serves the page and everything the page reads."""
    records = sorted(path.name for path in results.record_paths())
    reports = sorted(found.name for found in VERIFICATION_DIR.glob("*.json"))
    footprint = EVALUATION_DIR / "footprint.md"
    with _ResultsServer() as server:
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
        closed = []

        def get(path):
            connection.request("GET", path)
            answer = connection.getresponse()
            body = answer.read()
            if answer.will_close or answer.version != 11:
                closed.append(path)
            return answer.status, answer.getheader("Content-Type", ""), body

        def read_json(path, key):
            status, _, body = get(path)
            try:
                return status == 200 and key in json.loads(body)
            except ValueError:
                return False

        status, kind, body = get("/")
        _require(status == 200 and "text/html" in kind and body == (RESULTS_DIR / "index.html").read_bytes(),
                 "the server does not answer with the results page (status %d, %s)" % (status, kind))
        status, _, body = get(report.LIST_PATH)
        listed = json.loads(body) if status == 200 else None
        _require(listed is not None and sorted(listed) == records, "the list of records the server gives is not the "
                 "record files: %r" % (listed if listed is None else sorted(set(listed) ^ set(records))[:5],))
        unread = [name for name in listed if not read_json("/" + name, "host")]
        _require(not unread, "%d of the %d records could not be read from the server: %s"
                 % (len(unread), len(listed), ", ".join(unread[:3])))
        status, _, body = get(report.VERIFICATION_PATH + "list")
        _require(status == 200 and json.loads(body) == reports, "the list of verification records the server gives "
                 "is not the files in %s" % VERIFICATION_DIR.name)
        unread = [name for name in reports if not read_json(report.VERIFICATION_PATH + name, "checks")]
        _require(not unread, "verification records could not be read from the server: %s" % ", ".join(unread))
        _require(read_json("/" + results.ISSUES_FILE, "issues"), "the known issues could not be read from the server")
        _require(read_json("/" + results.MACHINES_FILE, "machines"), "what is stated about the hosts' machines could "
                 "not be read from the server")
        status, _, body = get(report.FOOTPRINT_PATH)
        _require(footprint.is_file() and status == 200 and body == footprint.read_bytes(),
                 "the server does not give the disk space and time values (status %d)" % status)
        _require(not closed, "the server closed its connection after %d of the requests, the first for %s"
                 % (len(closed), closed[0] if closed else ""))
        connection.close()
        lines = ["the results command served the page, and over one connection that it kept open: the list of "
                 "%d records and each record, %d verification records, the known issues, what is stated about "
                 "the machines, and the disk space and time values" % (len(records), len(reports))]
        address = _own_address()
        if address is None:
            lines.append("not checked: that the page cannot be reached from another machine (this host has no "
                         "network address of its own)")
        else:
            try:
                socket.create_connection((address, server.port), timeout=2).close()
                reached = True
            except OSError:
                reached = False
            _require(not reached, "the page is served on the host's network address too, not to this host only")
            lines.append("the server does not answer on the host's own network address: the page is served to "
                         "this host only")
    return lines


def _page_browser():
    """A browser that can render a page without a window and print what it
    made of it: Chrome, Chromium or Edge, where one is installed."""
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "chrome",
                 "msedge"):
        found = shutil.which(name, path=host.tool_path())
        if found:
            return found
    if host.host_os() == "macos":
        places = ["/Applications/%s.app/Contents/MacOS/%s" % (name, name)
                  for name in ("Google Chrome", "Chromium", "Microsoft Edge")]
    elif host.host_os() == "windows":
        roots = [os.environ.get(name) for name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData")]
        places = [os.path.join(root, *parts) for root in roots if root
                  for parts in (("Google", "Chrome", "Application", "chrome.exe"),
                                ("Microsoft", "Edge", "Application", "msedge.exe"))]
    else:
        places = []
    return next((place for place in places if os.path.isfile(place)), None)


def check_report_page():
    """The results page, rendered by a browser without a window."""
    browser = _page_browser()
    if not browser:
        raise CheckUnavailable("this host has no Chrome, Chromium or Edge to render the page with; none of them is "
                               "a host dependency. What the page reads is covered by the check report-serve")
    records = len(results.record_paths())
    with _ResultsServer() as server, tempfile.TemporaryDirectory(prefix="emu-verify-") as directory:
        try:
            done = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run",
                                   "--user-data-dir=" + directory, "--virtual-time-budget=8000", "--dump-dom",
                                   server.address], capture_output=True, text=True, timeout=180,
                                  stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CheckUnavailable("%s did not render the page: %s" % (os.path.basename(browser), error))
    if done.returncode != 0 or "<html" not in done.stdout:
        raise CheckUnavailable("%s did not render the page (status %d): %s"
                               % (os.path.basename(browser), done.returncode, done.stderr.strip()[-300:]))
    # What the page shows, without its own script and styles, which have
    # some of the same words in them.
    page = re.sub(r"<(script|style)\b.*?</\1>", "", done.stdout, flags=re.S)
    _require("%d records, read from this directory" % records in page,
             "the page does not say that it shows the %d records there are" % records)
    _require("could not be read" not in page, "the page says that records could not be read")
    for title in ("Hosts", "Platform support and known issues", "Disk space and times"):
        _require("<h2>%s</h2>" % title in page, "the page has no section \"%s\"" % title)
    counts = {name: page.count('class="%s"' % name) for name in ("card", "support", "issues", "footprint")}
    _require(counts["card"] > 0, "the page has no chart")
    _require(counts["support"] == 1 and counts["issues"] == 1, "the page has no support matrix or no list of "
             "known issues")
    _require(counts["footprint"] > 0, "the page has no table of disk space and times")
    return ["rendered without a window by %s, the page says that it shows %d records, which is the number of "
            "record files, and that none could not be read" % (os.path.basename(browser), records),
            "it has the hosts, the support matrix with the list of known issues, %d charts, and %d tables of disk "
            "space and times" % (counts["card"], counts["footprint"]),
            "not checked: choosing the hosts, relative values, and what pointing at a row or a cell shows"]


class _KeepBuildSteps:
    """The container runtime for the clean-up check: it does everything but
    remove build steps, which would empty the engine's store of them for
    other projects too. What it was asked to remove there is kept."""

    def __init__(self, runtime):
        self._runtime = runtime
        self.asked = []

    def __getattr__(self, name):
        return getattr(self._runtime, name)

    def run(self, *args, **kwargs):
        if args[:2] == ("builder", "prune"):
            self.asked.append(args)
            return subprocess.CompletedProcess(args, 0, "Total reclaimed space: 0B\n", "")
        return self._runtime.run(*args, **kwargs)


def check_build_cleanup():
    """What a build removes from the container engine afterwards, tried on
    stand-ins. Like a build, it also removes the project's own images of
    earlier builds, should the engine hold any."""
    runtime = container.detect()
    manifest = image.ensure("container", lambda: runtime, host.host_arch(), quiet=True)
    current = manifest["image_tag"]
    spec = image.definition()
    name, version = spec["name"], spec["version"]
    earlier = "%s:0.0.0-verify" % current.rsplit(":", 1)[0]
    foreign = "emu-verify-not-the-projects:standin"
    replaced = None

    def tags():
        listed = runtime.run("image", "ls", "--format", "{{.Repository}} {{.Tag}}")
        _require(listed.returncode == 0, "the container engine did not list its images: %s" % listed.stderr.strip())
        return {tuple(line.split()) for line in listed.stdout.splitlines() if len(line.split()) == 2}

    def ours(found):
        return {(repository, tag) for repository, tag in found
                if repository == name or repository.endswith("/" + name)}

    def has(found, wanted):
        repository, tag = wanted.rsplit(":", 1)
        return any(tag == t and (r == repository or r.endswith("/" + repository)) for r, t in found)

    try:
        for tag in (earlier, foreign):
            done = runtime.run("tag", current, tag)
            _require(done.returncode == 0, "could not make the stand-in %s: %s" % (tag, done.stderr.strip()))
        # An image without a name that carries the project's label, as the
        # image is that a later build of the same version took the tag from.
        created = runtime.run("create", current, "true")
        _require(created.returncode == 0, "could not make a stand-in container: %s" % created.stderr.strip())
        holder = created.stdout.strip().splitlines()[-1]
        committed = runtime.run("commit", "--change", "LABEL %s=%s" % (image.OWNER_LABEL, name), holder)
        runtime.run("rm", holder)
        _require(committed.returncode == 0, "could not make the stand-in for a replaced image: %s"
                 % committed.stderr.strip())
        replaced = committed.stdout.strip().splitlines()[-1]
        before = tags()
        _require(has(before, earlier) and has(before, foreign) and runtime.image_id(replaced),
                 "the stand-ins are not in the container engine")
        engine = _KeepBuildSteps(runtime)
        said = image.cleanup(engine)
        after = tags()
        _require(not has(after, earlier), "the project's image of another version stayed: %s" % earlier)
        _require(runtime.image_id(replaced) is None, "the image that a later build replaced stayed")
        _require(has(after, foreign), "an image that is not the project's was removed: %s" % foreign)
        kept = {(r, t) for r, t in ours(before) if t.startswith(version + "-")}
        _require(kept and kept <= after, "target images of the current version were removed: %s"
                 % ", ".join("%s:%s" % pair for pair in sorted(kept - after)))
        _require(not any(not t.startswith(version + "-") and t != "<none>" for _, t in ours(after)),
                 "images of other versions of the project stayed: %r" % sorted(ours(after)))
        _require(engine.asked == [("builder", "prune", "--force", "--filter", "until=" + image.CACHE_KEEP)],
                 "the clean-up did not ask the engine to remove the build steps unused for %s: %r"
                 % (image.CACHE_KEEP, engine.asked))
        _require(said and "of earlier builds" in said, "the clean-up did not say what it removed: %r" % (said,))
    finally:
        for left in (earlier, foreign) + ((replaced,) if replaced else ()):
            runtime.run("image", "rm", left)
    return ["with stand-ins in the container engine, the clean-up after a build removed the project's image of "
            "another version and the image a later build had replaced, and said so: %s" % said,
            "it left the %d target images of version %s and an image that is not the project's"
            % (len(kept), version),
            "it asked the engine to remove the build steps unused for %s; the check held that request back, so "
            "no build step was removed" % image.CACHE_KEEP,
            "not checked: the option that keeps earlier builds, and the removal of build steps itself"]


def _setup_record():
    named = os.environ.get("EMU_SETUP_RECORD")
    if named:
        return named
    if host.host_os() == "windows":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "tv-emu", "setup-installed")
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "tv-emu", "setup-installed")


# The setup script is only ever asked to check and to list here: never to
# install, and never to remove.
SETUP_CHECK = {"windows": ["-Check"]}.get(host.host_os(), ["--check"])
SETUP_LIST = {"windows": ["-Uninstall", "-Check"]}.get(host.host_os(), ["--uninstall", "--check"])


def check_setup():
    """The setup script's check without installing, and its list of what
    the uninstall option would remove."""
    script = ["cmd", "/c", str(ROOT / "setup.cmd")] if host.host_os() == "windows" else ["bash", str(ROOT / "setup.sh")]
    record = _setup_record()

    def recorded():
        try:
            with open(record, "rb") as handle:
                return handle.read()
        except OSError:
            return None

    def setup(arguments):
        done = subprocess.run(script + arguments, capture_output=True, text=True, timeout=900, cwd=str(ROOT),
                              stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout + done.stderr

    before = recorded()
    status, said = setup(SETUP_CHECK)
    _require(status in (0, 1), "asked to check only, the setup script ended with status %d: %s"
             % (status, said.strip()[-300:]))
    if status == 0:
        _require("All host dependencies are present" in said, "the check ended with success without saying that "
                 "every host dependency is present")
        found = "every host dependency is present"
    else:
        named = [line.strip() for line in said.splitlines() if line.strip().startswith("Missing:")]
        _require(named, "the check reported failure without naming what is missing")
        found = named[-1]
    _require(recorded() == before, "asked to check only, the setup script changed its record of what it installed")
    lines = ["asked to check only, the setup script ended with status %d: %s; its record of what it installed is "
             "unchanged" % (status, found)]
    status, said = setup(SETUP_LIST)
    _require(status == 0, "asked to list what the uninstall option would remove, the setup script ended with "
             "status %d: %s" % (status, said.strip()[-300:]))
    _require("Nothing was removed" in said or "Nothing to remove" in said, "the setup script did not say that it "
             "removed nothing")
    _require(recorded() == before, "asked to list only, the setup script changed its record")
    entries = 0 if before is None else sum(1 for line in before.decode(errors="replace").splitlines()
                                           if line.strip() and not line.startswith("#"))
    lines.append("asked to list what the uninstall option would remove, it listed and removed nothing; its record "
                 "has %d entries, as before" % entries)
    return lines + ["not checked: installing, asking before it, the optional extras and the package managers, "
                    "which need a host where something is missing"]


def check_vm_x86_64():
    """The simulated x86-64 guest: a diagnostic, outside the evaluation matrix."""
    modes = [mode["id"] for mode in catalog.matrix()["modes"]]
    _require(not any("x86" in mode for mode in modes), "the evaluation matrix has an x86-64 guest mode: %s"
             % ", ".join(modes))
    lines = ["the evaluation matrix has no x86-64 guest mode (%s)" % ", ".join(modes)]
    if host.host_arch() != "x86_64":
        manifest = image.load_manifest("vm", "x86_64")
        built = bool(manifest) and image.is_current(manifest) and all(
            (image.artifact_dir("vm", "x86_64") / name).is_file() for name in image.VM_FILES)
        if not built:
            raise CheckUnavailable("\n".join(lines + [
                "the x86-64 target image is not built on this host, and the check does not build it: the guest is "
                "a diagnostic, and the build takes time and disk space. \"emu build --mode vm --arch x86_64\" "
                "builds it"]))
    outcome = _prompt("vm", "x86_64")
    emulator = outcome.environment["emulator"]
    _require(outcome.ready["machine"] == "x86_64", "the target reports machine %s, expected x86_64"
             % outcome.ready["machine"])
    _require(emulator["accelerator"] == "tcg", "the x86-64 guest ran on %s, not on a simulated CPU"
             % emulator["accelerator"])
    return lines + ["x86_64 guest on %s simulating the CPU model %s booted in %.1fs and ran the prompt workload" % (
        emulator["accelerator"], emulator["cpu_model"], outcome.boot_seconds)]


def _command_checks():
    return {
        "doctor": (check_doctor, "9.2", "the launcher shows what it finds on the host, and names what is missing"),
        "report-serve": (check_report_serve, "9.2", "the results command serves the page and all that it reads"),
        "report-page": (check_report_page, "9.2", "the results page shows every record and its sections"),
        "build-cleanup": (check_build_cleanup, "9.2", "a build removes the project's earlier images and nothing "
                                                      "else"),
        "setup-check": (check_setup, "9.2", "the setup script checks and lists without installing or removing"),
        "vm-x86_64": (check_vm_x86_64, "9.2", "the simulated x86-64 guest starts, and is outside the matrix"),
    }


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
    "redrat-support": (check_redrat_support, "7.6", "learned profiles and focus-gated IR input pass software checks"),
    "redrat-device": (check_redrat_device, "7.6", "the host SDK detects, opens and closes an attached RedRat receiver"),
    "drivers-container": (check_drivers_container, "3.2", "emulated, mocked and host-routed drivers in container mode"),
    "drivers-vm": (check_drivers_vm, "3.2", "emulated, mocked and host-routed drivers in host-native VM mode"),
    "drivers-vm-arm32": (check_drivers_vm_arm32, "3.2", "the three driver strategies in an ARM32 VM"),
    "drivers-vm-arm64": (check_drivers_vm_arm64, "3.2", "the three driver strategies in an ARM64 VM"),
}
CHECKS.update(_graphics_checks())
CHECKS.update(_media_checks())
CHECKS.update(_web_checks())
CHECKS.update(_window_checks())
CHECKS.update(_stb_checks())
CHECKS.update(_command_checks())


def _report_path():
    """One record per host OS, host CPU architecture and machine."""
    return VERIFICATION_DIR / ("%s_%s.json" % (host.host_id(), host.machine_id()))


def _legacy_report_path():
    """Where the record was kept before machines were told apart: one per host
    OS and CPU architecture."""
    return VERIFICATION_DIR / ("%s.json" % host.host_id())


def _read_report(path):
    try:
        with open(path) as handle:
            found = json.load(handle)
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) and isinstance(found.get("checks"), dict) else None


def load_report():
    found = _read_report(_report_path())
    if found is None:
        # A record under the earlier name is this machine's only if it says so.
        legacy = _read_report(_legacy_report_path())
        if legacy and host.host_key(legacy.get("host") or {"id": ""}) == host.host_key():
            found = legacy
    return found or {"host": host.describe(), "checks": {}}


def arm_target_of(name):
    """The simulated ARM target that a check is for, by the check's name, or
    None."""
    for arch in armtargets.ARCHS:
        if name == "vm-" + arch or name.endswith("-vm-" + arch):
            return arch
    return None


def run_checks(names):
    """Run the named checks; returns how many ended in each status. A check
    for a simulated ARM target is not run on a host that is not set up for
    that target: it ends as unavailable, with the reason."""
    report = load_report()
    gaps = {}
    report["host"] = host.describe()
    # Outcomes of checks that no longer exist say nothing about this revision.
    report["checks"] = {name: entry for name, entry in report["checks"].items() if name in CHECKS}
    counts = {"pass": 0, "fail": 0, "unavailable": 0}
    for name in names:
        function, task, description = CHECKS[name]
        print("%-26s %s" % (name, description), flush=True)
        started = time.time()
        arch = arm_target_of(name)
        if arch and arch not in gaps:
            gaps[arch] = armtargets.gap(arch, container.detect)
        try:
            if gaps.get(arch):
                raise CheckUnavailable("%s\n%s" % (armtargets.not_set_up(arch, gaps[arch]), host.ARM_SETUP_HINT))
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
        # This machine's record under the earlier name is now in the new one.
        legacy = _read_report(_legacy_report_path())
        if legacy and host.host_key(legacy.get("host") or {"id": ""}) == host.host_key():
            _legacy_report_path().unlink()
    return counts
