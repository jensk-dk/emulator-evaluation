"""Command line of the startup launcher."""
import argparse
import statistics
import sys

from . import catalog, container, drivers as driver_features, graphics, host, image, results, verify, vm
from .errors import EmuError
from .run import DEFAULT_CPUS, DEFAULT_MEMORY_MB, KNOWN_OPTIONS, RunOptions, launch

EPILOG = """\
examples:
  emu run                                      interactive prompt in container mode
  emu run --mode vm                            interactive prompt in a host-native VM
  emu run --mode vm --arch arm32 --workload bench --record
  emu run --mode container --workload driver-check --driver hwrng=host
  emu run --mode vm --option accel=tcg --option cpu=max
  emu run --mode vm --workload graphics-demo --resolution 4k --record
  emu run --workload graphics-demo --graphics emulated --screenshot shots -- --tests gles,vulkan
  emu verify                                   run every verification check on this host

In an interactive VM prompt, Ctrl-A X quits the emulator.
"""


def _options(pairs):
    options = {}
    for pair in pairs or []:
        key, separator, value = pair.partition("=")
        if not separator:
            raise EmuError("bad --option %r: expected KEY=VALUE" % pair)
        options[key] = value
    return options


def _print_summary(outcomes):
    """Median of each measurement across the runs just made."""
    tests = {}
    for outcome in outcomes:
        for result in outcome.results:
            if isinstance(result.get("value"), (int, float)):
                tests.setdefault((result["area"], result["test"], result["unit"]), []).append(result["value"])
    if not tests:
        return
    print("\n%-20s %-16s %14s  %s" % ("area", "test", "median", "unit"))
    for (area, test, unit), values in tests.items():
        spread = "  (min %.1f, max %.1f, n=%d)" % (min(values), max(values), len(values)) if len(values) > 1 else ""
        print("%-20s %-16s %14.1f  %s%s" % (area, test, statistics.median(values), unit, spread))


def cmd_run(args):
    declared = catalog.workload(args.workload)
    if declared is None:
        known = ", ".join(w["id"] for w in catalog.workloads()["workloads"])
        raise EmuError("unknown workload %r (known: %s)" % (args.workload, known))
    if declared["status"] != "implemented":
        raise EmuError("workload %r is defined but not implemented yet (scheduled for stage %s)"
                       % (args.workload, declared["stage"]))
    workload_args = list(args.workload_args)
    if workload_args[:1] == ["--"]:
        workload_args = workload_args[1:]
    outcomes = []
    for index in range(args.repeat):
        opts = RunOptions(
            mode=args.mode, workload=args.workload, args=workload_args, arch=args.arch, cpus=args.cpus,
            memory_mb=args.memory, drivers=driver_features.parse(args.driver), options=_options(args.option),
            extra_args=args.emulator_arg or [], timeout=args.timeout, rebuild=args.rebuild and index == 0,
            resolution=args.resolution, graphics=args.graphics, screenshot_dir=args.screenshot)
        outcome = launch(opts)
        outcomes.append(outcome)
        if outcome.attached:
            return outcome.process_exit
        if outcome.timed_out:
            print("emu: timed out after %s seconds" % args.timeout, file=sys.stderr)
            return 124
        if outcome.exit_code is None:
            print("emu: the emulator stopped before the workload reported an exit status (emulator exit %s)"
                  % outcome.process_exit, file=sys.stderr)
            return 70
        for screen in outcome.screens:
            if screen.get("file"):
                print("emu: captured the display (%dx%d) to %s" % (screen["captured_width"],
                                                                 screen["captured_height"], screen["file"]),
                      file=sys.stderr)
            else:
                print("emu: could not capture the display: %s" % screen.get("error"), file=sys.stderr)
        if args.record:
            if outcome.exit_code != 0:
                print("emu: not recording a failed run", file=sys.stderr)
            else:
                path = results.write(results.build(outcome, opts))
                print("emu: recorded %s" % path, file=sys.stderr)
        if outcome.exit_code != 0:
            return outcome.exit_code
    if args.workload != "prompt":
        _print_summary(outcomes)
    return 0


def cmd_build(args):
    modes = ("container", "vm") if args.mode == "all" else (args.mode,)
    native = host.host_arch()
    for mode in modes:
        if mode == "container":
            archs = (native,)
        elif args.arch == "all":
            archs = sorted({native, "arm32", "arm64"})
        else:
            archs = (native if args.arch == "native" else args.arch,)
        for arch in archs:
            manifest = image.ensure(mode, container.detect, arch, rebuild=args.rebuild)
            print("emu: %s image for %s is current (definition %s)" % (mode, arch, manifest["definition_sha256"][:12]))
    return 0


def cmd_doctor(args):
    info = host.describe()
    print("host        %s %s, %s, %s CPUs, %s" % (
        info["os"], info["os_version"], info["cpu_model"] or info["arch"], info["cpus"],
        "%.0f GiB" % (info["memory_bytes"] / 2**30) if info["memory_bytes"] else "unknown memory"))
    problems = 0
    native = host.host_arch()
    for arch in sorted({native, "arm64", "arm32"}):
        binary = host.find_tool(vm.QEMU_BINARY[arch])
        role = "host-native and ARM64 guests" if arch == native == "arm64" else \
               "host-native guests" if arch == native else "%s guests" % arch.upper()
        if binary:
            print("qemu        %s: %s (%s)" % (role, vm.qemu_version(binary), binary))
        else:
            print("qemu        %s: MISSING %s" % (role, vm.QEMU_BINARY[arch]))
            problems += 1
    resolved = vm.resolve("native")
    print("accelerator %s for host-native VM mode%s" % (
        resolved["accelerator"], " (no hardware virtualization available)" if resolved["notes"] else ""))
    try:
        runtime = container.detect(start_engine=False)
        engine = runtime.engine_info()
        print("container   %s; engine has %s CPUs, %s" % (
            runtime.version(), engine.get("cpus"),
            "%.1f GiB" % (engine["memory_bytes"] / 2**30) if engine.get("memory_bytes") else "unknown memory"))
    except EmuError as error:
        print("container   MISSING: %s" % error)
        runtime = None
        problems += 1
    binary = host.find_tool(vm.QEMU_BINARY[native])
    if binary:
        probe = graphics.probe_vm(binary)
        print("graphics    VM mode: %s" % ("host acceleration available: " + probe["reason"] if probe["available"]
                                           else "emulated only: " + probe["reason"]))
    if runtime:
        manifest = image.load_manifest("container", native)
        if manifest and runtime.image_id(manifest["image_tag"]):
            probe = graphics.probe_container(runtime, manifest["image_tag"], manifest["platform"])
            print("graphics    container mode: %s" % (
                "host acceleration available: " + probe["reason"] if probe["available"]
                else "emulated only: " + probe["reason"]))
    for kind, archs in (("container", (native,)), ("vm", sorted({native, "arm32", "arm64"}))):
        for arch in archs:
            manifest = image.load_manifest(kind, arch)
            state = "not built" if not manifest else "current" if image.is_current(manifest) else "out of date"
            print("image       %-9s %-6s %s" % (kind, arch, state))
    if problems:
        print("\n%s" % host.SETUP_HINT)
    return 1 if problems else 0


def cmd_matrix(args):
    data = catalog.matrix()
    print("%-16s %s" % ("host", "  ".join(m["id"] for m in data["modes"])))
    for h in data["hosts"]:
        print("%-16s %s" % (h["id"], "  ".join("x".center(len(m["id"])) for m in data["modes"])))
    print("\nperformance areas: " + ", ".join(data["performance_areas"]))
    if args.verify:
        problems = catalog.verify_matrix()
        for problem in problems:
            print("PROBLEM: " + problem)
        print("matrix verification: %s" % ("FAILED" if problems else "ok"))
        return 1 if problems else 0
    return 0


def cmd_workloads(args):
    for item in catalog.workloads()["workloads"]:
        areas = sorted({m["area"] for m in item.get("measurements", [])})
        print("%-14s %-7s %-12s stage %s  %s" % (item["id"], item["version"], item["status"], item["stage"],
                                                 ", ".join(areas) or item["kind"]))
    if args.verify:
        problems = catalog.verify_workloads()
        for problem in problems:
            print("PROBLEM: " + problem)
        print("workload verification: %s" % ("FAILED" if problems else "ok"))
        return 1 if problems else 0
    return 0


def cmd_verify(args):
    if args.list:
        for name, (_, task, description) in verify.CHECKS.items():
            print("%-26s task %-9s %s" % (name, task, description))
        return 0
    names = args.checks or list(verify.CHECKS)
    for name in names:
        if name not in verify.CHECKS:
            raise EmuError("unknown check %r (see: emu verify --list)" % name)
    counts = verify.run_checks(names)
    summary = "%d of %d checks passed on %s" % (counts["pass"], len(names), host.host_id())
    if counts["unavailable"]:
        summary += "; %d could not be run on this host" % counts["unavailable"]
    if counts["fail"]:
        summary += "; %d failed" % counts["fail"]
    print("\n" + summary)
    return 1 if counts["fail"] else 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="emu", description="Startup launcher for the emulator evaluation platform.", epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = commands.add_parser(
        "run", help="launch the emulator and run a target OS workload", epilog=(
            "emulator options (--option KEY=VALUE):\n" +
            "\n".join("  %-14s %s" % item for item in sorted(KNOWN_OPTIONS.items())) +
            "\n\ndriver features (--driver FEATURE=STRATEGY, STRATEGY one of emulated, mocked, host, none):\n" +
            "\n".join("  %-14s %s" % item for item in sorted(driver_features.FEATURES.items()))),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    run.add_argument("--mode", choices=("container", "vm"), default="container",
                     help="emulator execution mode (default: container)")
    run.add_argument("--arch", choices=("native", "arm32", "arm64", "x86_64"), default="native",
                     help="VM guest CPU architecture (default: native, the host's own)")
    run.add_argument("--workload", default="prompt", metavar="NAME",
                     help="target OS workload: prompt, bench, driver-check, graphics-demo "
                          "(default: prompt; see: emu workloads)")
    run.add_argument("--cpus", type=int, default=DEFAULT_CPUS, help="CPUs given to the target (default: %(default)s)")
    run.add_argument("--memory", type=int, default=DEFAULT_MEMORY_MB, metavar="MIB",
                     help="memory given to the target in MiB (default: %(default)s)")
    run.add_argument("--resolution", choices=tuple(graphics.RESOLUTIONS), metavar="RESOLUTION",
                     help="display resolution: 720p, 1080p or 4k (default: 1080p). The emulator has a display "
                          "when the workload uses one or this or --graphics is given")
    run.add_argument("--graphics", choices=graphics.CHOICES,
                     help="how graphics are provided: host maps them to the host's graphics acceleration, "
                          "emulated renders on the target CPU, auto prefers host and falls back to emulated "
                          "(default: auto)")
    run.add_argument("--screenshot", metavar="DIR",
                     help="save a PNG of the display to DIR each time a graphics workload has a finished frame up")
    run.add_argument("--driver", action="append", metavar="FEATURE=STRATEGY",
                     help="how a target driver feature is provided; repeatable")
    run.add_argument("--option", action="append", metavar="KEY=VALUE", help="emulator option; repeatable")
    run.add_argument("--emulator-arg", action="append", metavar="ARG",
                     help="extra argument passed to qemu or the container runtime; repeatable")
    run.add_argument("--record", action="store_true", help="write the results to evaluation/results/")
    run.add_argument("--repeat", type=int, default=1, metavar="N", help="run the workload N times, each from a fresh start")
    run.add_argument("--timeout", type=float, metavar="SECONDS", help="stop the emulator after this long")
    run.add_argument("--rebuild", action="store_true", help="rebuild the target image first")
    run.add_argument("workload_args", nargs=argparse.REMAINDER, metavar="-- WORKLOAD_ARGS",
                     help="arguments for the workload, after --")
    run.set_defaults(function=cmd_run)

    build = commands.add_parser("build", help="build the target OS image")
    build.add_argument("--mode", choices=("container", "vm", "all"), default="all")
    build.add_argument("--arch", choices=("native", "arm32", "arm64", "x86_64", "all"), default="native",
                       help="VM image architecture (default: native)")
    build.add_argument("--rebuild", action="store_true", help="build even if the image is current")
    build.set_defaults(function=cmd_build)

    doctor = commands.add_parser("doctor", help="show the host, its dependencies and the built images")
    doctor.set_defaults(function=cmd_doctor)

    matrix = commands.add_parser("matrix", help="show the host and mode test matrix")
    matrix.add_argument("--verify", action="store_true", help="check that the matrix is complete")
    matrix.set_defaults(function=cmd_matrix)

    workloads = commands.add_parser("workloads", help="list the evaluation workloads")
    workloads.add_argument("--verify", action="store_true", help="check that the workloads cover every performance area")
    workloads.set_defaults(function=cmd_workloads)

    check = commands.add_parser("verify", help="run verification checks on this host")
    check.add_argument("checks", nargs="*", metavar="CHECK", help="checks to run (default: all)")
    check.add_argument("--list", action="store_true", help="list the checks")
    check.set_defaults(function=cmd_verify)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        return args.function(args)
    except EmuError as error:
        print("emu: %s" % error, file=sys.stderr)
        if error.hint:
            print("emu: %s" % error.hint, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
