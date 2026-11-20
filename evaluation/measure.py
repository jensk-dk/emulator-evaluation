#!/usr/bin/env python3
"""Measure this host: the installation, the targets and the performance.

    python3 evaluation/measure.py run                 every stage but install
    python3 evaluation/measure.py run --install       the installation first
    python3 evaluation/measure.py run --stages performance,verify
    python3 evaluation/measure.py run --dry-run       say what would be done
    python3 evaluation/measure.py table               this host's values

One command for what evaluation/procedures.md asks of a host ("Disk space
and times", and the performance runs). The stages, in the order they run:

  install         only when named, or with --install. Removes the host
                  installation with the setup script's uninstall option and
                  the downloads its tools kept, then times the setup script
                  (with --yes and, unless --no-arm-targets, --arm-targets)
                  and takes the space the installation uses.
  build-each      for each target of the host: removes the project's images
                  and the whole build cache from the container engine, then
                  times "emu build --rebuild" for that target alone.
  build-together  the same once, then every target one after the other.
  sizes           the size of each built target, and of every place the
                  installation uses.
  performance     every implemented performance workload in every emulator
                  mode: "emu run --record --repeat 3".
  verify          "emu verify": the installation that was measured has to be
                  one that works.

The performance runs write their records to evaluation/results, and the
verification writes its own to evaluation/verification, as always. The other
values go to evaluation/footprint/HOST_MACHINE.json, one file per host and
machine; a stage that runs again replaces its earlier values there. The
output of every command is kept in build/measure/, which is not version
controlled. `table` prints the values of the file as rows for the host's
table in evaluation/footprint.md.

A step that fails does not stop the others: it is in the record as failed,
and the command reports failure at its end. A value that was not taken is not
in the record, and reads "not measured".

What is removed is said first, and asked about unless --yes is given. The
install stage needs someone at the host: an administrator's password on
Linux and macOS, the installers' elevation prompts on Windows.
"""
import argparse
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluation"))

from emulator import catalog, container, host, image, results          # noqa: E402
from emulator.paths import BUILD_DIR, EVALUATION_DIR, RESULTS_DIR      # noqa: E402

SCHEMA_VERSION = 1
FOOTPRINT_DIR = EVALUATION_DIR / "footprint"
STAGES = ("install", "build-each", "build-together", "sizes", "performance", "verify")
DEFAULT_STAGES = STAGES[1:]
WINDOWS = os.name == "nt"


# ------------------------------------------------------------------ helpers ---

def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _say(text=""):
    print(text, flush=True)


def record_path():
    return FOOTPRINT_DIR / ("%s_%s.json" % (host.host_id(), host.machine_id()))


def _load():
    try:
        with open(record_path()) as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("measurements"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"schema_version": SCHEMA_VERSION, "measurements": {}}


def _save(data):
    data["schema_version"] = SCHEMA_VERSION
    data["host"] = host.describe()
    FOOTPRINT_DIR.mkdir(parents=True, exist_ok=True)
    with open(record_path(), "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def _stamp(values):
    """What every stage's values are kept with: when, and of which source."""
    spec = image.definition()
    values.update({"taken_at": _now(), "revision": image.git_revision(),
                   "image": {"version": spec["version"], "definition_sha256": image.definition_sha256()}})
    return values


def emu(*args):
    """The launcher, as ./emu and emu.cmd start it."""
    return [sys.executable, "-m", "emulator"] + list(args)


def _shown(command):
    """A command as someone would type it."""
    if command[:3] == [sys.executable, "-m", "emulator"]:
        command = ["emu.cmd" if WINDOWS else "./emu"] + command[3:]
    return " ".join(str(part) for part in command)


def setup(*options):
    """The setup script with options given as for setup.sh (--yes)."""
    if WINDOWS:
        named = ["-" + "".join(word.capitalize() for word in option.lstrip("-").split("-")) for option in options]
        return ["cmd", "/c", str(ROOT / "setup.cmd")] + named
    return [str(ROOT / "setup.sh")] + list(options)


class Runner:
    def __init__(self, dry_run):
        self.dry_run = dry_run
        self.failed = []
        self.logs = BUILD_DIR / "measure" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.count = 0

    def run(self, command, label, env=None):
        """Run a command with its output shown and kept. Returns its exit
        status, its running time in seconds and its output."""
        self.count += 1
        _say("\n=== %s\n    %s" % (label, _shown(command)))
        if self.dry_run:
            return 0, 0.0, ""
        self.logs.mkdir(parents=True, exist_ok=True)
        log = self.logs / ("%02d-%s.log" % (self.count, "".join(c if c.isalnum() else "-" for c in label)))
        full = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
        full.update(env or {})
        said = []
        started = time.monotonic()
        try:
            process = subprocess.Popen([str(part) for part in command], cwd=str(ROOT), env=full,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as error:
            _say("    could not be started: %s" % error)
            self.failed.append(label)
            return 127, 0.0, str(error)
        with open(log, "wb") as kept:
            while True:
                chunk = process.stdout.read1(65536)
                if not chunk:
                    break
                kept.write(chunk)
                said.append(chunk)
                sys.stdout.write(chunk.decode("utf-8", "replace"))
                sys.stdout.flush()
        status = process.wait()
        seconds = round(time.monotonic() - started, 1)
        _say("=== %s: exit status %d after %s" % (label, status, _duration(seconds)))
        if status != 0:
            self.failed.append(label)
        return status, seconds, b"".join(said).decode("utf-8", "replace")


def _duration(seconds):
    if seconds is None:
        return "not measured"
    return "%.0f s" % seconds if seconds < 120 else "%.1f min" % (seconds / 60.0)


def _size(count):
    if count is None:
        return "not measured"
    return "%.2f GB" % (count / 1e9) if count >= 1e9 else "%.0f MB" % (count / 1e6)


def tree_bytes(path):
    """The space the files under a path take, as du counts it: allocated
    blocks, a file with several names once, links not followed. None where
    there is nothing, or where it cannot be read."""
    path = pathlib.Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    seen, total = set(), 0

    def add(entry_path):
        nonlocal total
        try:
            status = os.lstat(entry_path)
        except OSError:
            return
        if status.st_nlink > 1 and not WINDOWS:
            key = (status.st_dev, status.st_ino)
            if key in seen:
                return
            seen.add(key)
        total += status.st_size if WINDOWS else status.st_blocks * 512

    if not path.is_dir() or path.is_symlink():
        add(path)
        return total
    unreadable = []
    for folder, _names, files in os.walk(str(path), onerror=unreadable.append):
        add(folder)
        for name in files:
            add(os.path.join(folder, name))
    return None if unreadable and not total else total


def _volume_used():
    return shutil.disk_usage(str(ROOT)).used


def setup_record():
    """The setup script's record of what it installed on this host."""
    named = os.environ.get("EMU_SETUP_RECORD")
    if named:
        return pathlib.Path(named)
    if WINDOWS:
        return pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "tv-emu" / "setup-installed"
    state = os.environ.get("XDG_STATE_HOME") or str(pathlib.Path.home() / ".local" / "state")
    return pathlib.Path(state) / "tv-emu" / "setup-installed"


def _recorded(kinds):
    found = []
    try:
        for line in setup_record().read_text().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] in kinds:
                found.append(parts[1].strip())
    except OSError:
        pass
    return found


def kept_downloads():
    """Where the installation's tools keep what they downloaded."""
    home = pathlib.Path.home()
    system = host.host_os()
    if system == "macos":
        return [home / "Library" / "Caches" / name for name in ("Homebrew", "colima", "pip")]
    if system == "windows":
        return [pathlib.Path(os.environ.get("LOCALAPPDATA", str(home))) / "pip" / "Cache"]
    return [home / ".cache" / "pip", pathlib.Path("/var/cache/apt/archives")]


def places():
    """Every place the host installation uses, with its size in bytes (None:
    not there, or not readable). procedures.md names them per host OS."""
    home = pathlib.Path.home()
    system = host.host_os()
    named = [("the project's own host software (build/host)", BUILD_DIR / "host")]
    if system == "macos":
        named += [("Homebrew with its packages (/opt/homebrew)", pathlib.Path("/opt/homebrew")),
                  ("the container engine's virtual machine (~/.colima)", home / ".colima"),
                  ("the container client's files (~/.docker)", home / ".docker")]
    elif system == "windows":
        named += [("QEMU", pathlib.Path(r"C:\Program Files\qemu")),
                  ("Podman", pathlib.Path(r"C:\Program Files\RedHat\Podman")),
                  ("Podman's machine and its downloads (~\\.local\\share\\containers)",
                   home / ".local" / "share" / "containers")]
    else:
        named += [("rootless container storage (~/.local/share/containers)", home / ".local" / "share" / "containers")]
    named += [("kept downloads (%s)" % path, path) for path in kept_downloads()]
    found = [{"what": what.replace(str(home), "~"), "path": str(path).replace(str(home), "~"),
              "bytes": tree_bytes(path)} for what, path in named]
    if system == "linux":
        found.append(_linux_packages())
        found.append(_linux_engine())
    return found


def _linux_packages():
    """The files of the packages the setup script's record lists (apt)."""
    packages = _recorded(("apt", "apt-dep"))
    entry = {"what": "the %d packages the setup script installed (dpkg -L)" % len(packages), "path": None, "bytes": None}
    if not packages or not shutil.which("dpkg"):
        return entry
    seen, total = set(), 0
    for package in packages:
        listed = subprocess.run(["dpkg", "-L", package], capture_output=True, text=True)
        for name in listed.stdout.splitlines() if listed.returncode == 0 else ():
            try:
                status = os.lstat(name)
            except OSError:
                continue
            if os.path.isdir(name) and not os.path.islink(name):
                continue
            if (status.st_dev, status.st_ino) not in seen:
                seen.add((status.st_dev, status.st_ino))
                total += status.st_blocks * 512
    entry["bytes"] = total
    return entry


def _linux_engine():
    """Docker's storage, which only root reads: asked for without a prompt."""
    entry = {"what": "the container engine's storage (/var/lib/docker)", "path": "/var/lib/docker", "bytes": None}
    if os.path.isdir("/var/lib/docker") and shutil.which("sudo"):
        asked = subprocess.run(["sudo", "-n", "du", "-sk", "/var/lib/docker"], capture_output=True, text=True)
        if asked.returncode == 0 and asked.stdout.split():
            entry["bytes"] = int(asked.stdout.split()[0]) * 1024
        else:
            entry["unavailable"] = "needs root: run \"sudo -v\" first"
    return entry


def targets(arm):
    """The targets this host builds, as (name, mode, arch for emu build)."""
    native = host.host_arch()
    found = [("container", "container", "native"), ("vm-%s" % native, "vm", "native")]
    for arch in ("arm64", "arm32"):
        if arm and arch != native:
            found.append(("vm-%s" % arch, "vm", arch))
    return found


def modes(arm):
    found = [("container", ["--mode", "container"]), ("vm-native", ["--mode", "vm", "--arch", "native"])]
    if arm:
        found += [("vm-arm64", ["--mode", "vm", "--arch", "arm64"]), ("vm-arm32", ["--mode", "vm", "--arch", "arm32"])]
    return found


def _confirm(args, lines):
    _say("\nThis will:")
    for line in lines:
        _say("  - " + line)
    if args.yes or args.dry_run:
        return True
    if not sys.stdin.isatty():
        _say("Not running interactively; run again with --yes to go ahead.")
        return False
    return input("Go ahead? [y/N] ").strip().lower() in ("y", "yes")


# ------------------------------------------------------------------- stages ---

def stage_install(args, runner, data):
    if not setup_record().is_file() and not args.dry_run:
        _say("install: the setup script has no record on this host (%s), so there is nothing it would remove and "
             "install again; not measured" % setup_record())
        runner.failed.append("install")
        return
    arm = [] if args.no_arm_targets else ["--arm-targets"]
    downloads = [] if args.keep_downloads else kept_downloads()
    aside = None
    sudo = not WINDOWS and shutil.which("sudo")
    values = {"steps": []}
    if sudo and not args.dry_run:
        subprocess.run(["sudo", "-v"])
    status, seconds, _ = runner.run(setup("--uninstall", "--yes"), "remove the installation")
    values["steps"].append({"command": _shown(setup("--uninstall", "--yes")), "exit_status": status, "seconds": seconds})
    removed = []
    for path in downloads:
        if args.dry_run or not path.exists():
            continue
        if host.host_os() == "linux" and path == pathlib.Path("/var/cache/apt/archives"):
            if shutil.which("apt-get"):
                runner.run(["sudo", "apt-get", "clean"], "empty the package manager's downloads")
                removed.append(str(path))
        elif host.host_os() == "linux":
            aside = path.with_name(path.name + ".measure-aside")       # other projects use pip's cache
            if not aside.exists():
                path.rename(aside)
                removed.append("%s (moved aside, put back afterwards)" % path)
            else:
                aside = None
        else:
            shutil.rmtree(str(path), ignore_errors=True)
            removed.append(str(path))
    values["downloads_removed"] = removed
    if sudo and not args.dry_run:
        subprocess.run(["sudo", "-v"])                                  # the removal makes sudo forget
    before = _volume_used()
    command = setup("--yes", *arm)
    status, seconds, _ = runner.run(command, "install", env={"NONINTERACTIVE": "1"})
    values.update({"command": _shown(command), "exit_status": status, "seconds": seconds,
                   "arm_targets": bool(arm), "volume_used_before_bytes": before,
                   "volume_grew_bytes": _volume_used() - before})
    if not args.dry_run:
        values["places"] = places()
        values["places_bytes"] = sum(place["bytes"] or 0 for place in values["places"])
    if aside is not None:
        current = aside.with_name(aside.name[:-len(".measure-aside")])
        shutil.rmtree(str(current), ignore_errors=True)
        aside.rename(current)
    if not args.dry_run:
        data["measurements"]["install"] = _stamp(values)
        _save(data)


def _empty_engine(runtime, runner):
    """Take the project's images and every kept build step out of the
    container engine, so that a build has nothing to start from."""
    name = image.definition()["name"]
    listed = runtime.run("image", "ls", "--all", "--quiet", "--filter", "label=%s=%s" % (image.OWNER_LABEL, name))
    ids = sorted(set(listed.stdout.split())) if listed.returncode == 0 else []
    tagged = runtime.run("image", "ls", "--format", "{{.Repository}}:{{.Tag}}")
    ours = [line for line in tagged.stdout.split() if line.split(":")[0].rsplit("/", 1)[-1] == name
            and not line.endswith(":<none>")] if tagged.returncode == 0 else []
    for reference in ours + ids + [image._base_image(image.definition())]:
        runtime.run("image", "rm", "--force", reference)
    if runtime.name == "podman":
        runtime.run("image", "prune", "--force", timeout=600)           # its build steps are untagged images
    status, _, _ = runner.run([runtime.cli, "builder", "prune", "--all", "--force"], "empty the build cache")
    return status == 0


def _timed_build(runner, name, mode, arch):
    command = emu("build", "--mode", mode, "--arch", arch, "--rebuild")
    status, seconds, output = runner.run(command, "build %s" % name)
    cached = sum(1 for line in output.splitlines() if " CACHED" in line or "Using cache" in line)
    return {"target": name, "command": _shown(command), "exit_status": status, "seconds": seconds,
            "steps_from_cache": cached}


def _engine(args):
    if args.dry_run:
        try:
            return container.detect(start_engine=False)
        except Exception:
            return None
    return container.detect()


def stage_build_each(args, runner, data):
    runtime = _engine(args)
    builds = {}
    for name, mode, arch in targets(not args.no_arm_targets):
        emptied = _empty_engine(runtime, runner) if runtime and not args.dry_run else None
        builds[name] = _timed_build(runner, name, mode, arch)
        builds[name]["engine_emptied"] = emptied
    if not args.dry_run:
        data["measurements"]["build_each"] = _stamp({"engine": runtime.version(), "builds": builds})
        _save(data)


def stage_build_together(args, runner, data):
    runtime = _engine(args)
    emptied = _empty_engine(runtime, runner) if runtime and not args.dry_run else None
    builds = [_timed_build(runner, name, mode, arch) for name, mode, arch in targets(not args.no_arm_targets)]
    if not args.dry_run:
        data["measurements"]["build_together"] = _stamp({
            "engine": runtime.version(), "engine_emptied": emptied, "builds": builds,
            "seconds": round(sum(build["seconds"] for build in builds), 1)})
        _save(data)


def stage_sizes(args, runner, data):
    import footprint
    _say("\n=== sizes")
    if args.dry_run:
        _say("    the built targets, and: %s" % ", ".join(str(place["path"] or place["what"]) for place in places()))
        return
    found = footprint.target_sizes()
    measured = places()
    for target in found:
        _say("    %-28s %s" % (target["target"], _size(target["bytes"])))
    for place in measured:
        _say("    %-28s %s" % (_size(place["bytes"]), place["what"]))
    data["measurements"]["sizes"] = _stamp({"targets": found, "places": measured,
                                            "places_bytes": sum(place["bytes"] or 0 for place in measured),
                                            "volume_used_bytes": _volume_used()})
    _save(data)


def performance_workloads():
    return [item["id"] for item in catalog.workloads()["workloads"]
            if item.get("kind") == "performance" and item.get("status") == "implemented"]


def stage_performance(args, runner, data):
    by_mode = {}
    for mode, options in modes(not args.no_arm_targets):
        runs = by_mode.setdefault(mode, {})
        for workload in performance_workloads():
            before = set(results.record_paths())
            command = emu("run", *options, "--workload", workload, "--record", "--repeat", str(args.repeat))
            if args.mute:
                command.append("--mute")
            status, seconds, _ = runner.run(command, "%s in %s" % (workload, mode))
            new = sorted(set(results.record_paths()) - before)
            durations = []
            for path in new:
                try:
                    durations.append(json.loads(path.read_text()).get("duration_seconds"))
                except (OSError, ValueError):
                    durations.append(None)
            runs[workload] = {"command": _shown(command), "exit_status": status, "seconds": seconds,
                              "records": [path.name for path in new], "run_seconds": durations}
            if not args.dry_run and len(new) != args.repeat:
                runner.failed.append("%s in %s: %d of %d runs recorded" % (workload, mode, len(new), args.repeat))
    if not args.dry_run:
        data["measurements"]["performance"] = _stamp({"repeat": args.repeat, "muted": args.mute, "modes": by_mode})
        _save(data)


def stage_verify(args, runner, data):
    from emulator import verify
    status, seconds, _ = runner.run(emu("verify"), "verify")
    if args.dry_run:
        return
    counts = {}
    try:
        checks = json.loads(verify._report_path().read_text())["checks"]
        for check in checks.values():
            counts[check["status"]] = counts.get(check["status"], 0) + 1
    except (OSError, ValueError, KeyError):
        pass
    data["measurements"]["verify"] = _stamp({"command": _shown(emu("verify")), "exit_status": status,
                                             "seconds": seconds, "checks": counts})
    _save(data)


RUN = {"install": stage_install, "build-each": stage_build_each, "build-together": stage_build_together,
       "sizes": stage_sizes, "performance": stage_performance, "verify": stage_verify}


def run(args):
    chosen = [name.strip() for name in args.stages.split(",") if name.strip()] if args.stages else list(DEFAULT_STAGES)
    unknown = [name for name in chosen if name not in STAGES]
    if unknown:
        _say("unknown stage: %s (the stages are: %s)" % (", ".join(unknown), ", ".join(STAGES)))
        return 2
    if args.install and "install" not in chosen:
        chosen.append("install")
    chosen = [name for name in STAGES if name in chosen]
    arm = not args.no_arm_targets
    names = ", ".join(name for name, _mode, _arch in targets(arm))
    will = []
    if "install" in chosen:
        will.append("remove the host installation (%s), which takes the built container images with it where it "
                    "removes the container engine" % _shown(setup("--uninstall", "--yes")))
        if not args.keep_downloads:
            will.append("remove the downloads its tools kept: %s (on Linux pip's are moved aside and put back)"
                        % ", ".join(str(path) for path in kept_downloads()))
        will.append("install again and time it: %s" % _shown(setup("--yes", *(["--arm-targets"] if arm else []))))
    if "build-each" in chosen or "build-together" in chosen:
        will.append("remove this project's images and its base image from the container engine, and the engine's "
                    "whole build cache, which holds the build steps of other projects too")
        will.append("build from nothing, timed: %s%s" % (names, ", each alone and then all one after the other"
                                                         if "build-each" in chosen and "build-together" in chosen else ""))
    if "sizes" in chosen:
        will.append("take the sizes of the targets and of the installation's places")
    if "performance" in chosen:
        will.append("run %s in %s, %d times each, and record the results" % (
            ", ".join(performance_workloads()), ", ".join(mode for mode, _ in modes(arm)), args.repeat))
    if "verify" in chosen:
        will.append("run every verification check (its window checks need an unlocked screen)")
    _say("Measuring %s on machine %s; values go to %s" % (host.host_id(), host.machine_id(),
                                                          record_path().relative_to(ROOT)))
    if not _confirm(args, will):
        return 1
    runner = Runner(args.dry_run)
    data = _load()
    for name in chosen:
        try:
            RUN[name](args, runner, data)
        except Exception as error:                  # one stage's failure is not the others'
            _say("%s: failed: %s" % (name, error))
            runner.failed.append(name)
    _say()
    if args.dry_run:
        _say("Dry run: nothing was run, removed or recorded.")
        return 0
    _say("Output of every command: %s" % runner.logs.relative_to(ROOT))
    _say("Values: %s (\"measure.py table\" prints them as rows for evaluation/footprint.md)"
         % record_path().relative_to(ROOT))
    if runner.failed:
        _say("FAILED: " + "; ".join(runner.failed))
        return 1
    return 0


# -------------------------------------------------------------------- table ---

def _date(values):
    return (values or {}).get("taken_at", "")[:10]


def table(args):
    path = pathlib.Path(args.file) if args.file else record_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        _say("no values in %s: \"measure.py run\" takes them" % path)
        return 1
    taken = data["measurements"]
    described = data.get("host") or {}
    _say("### %s on %s\n" % (described.get("id"), described.get("machine")))
    _say("%s, %s. Taken with `evaluation/measure.py`.\n" % (described.get("cpu_model"), described.get("os_version")))
    _say("| What | Disk space | Time | Taken |")
    _say("|---|---|---|---|")
    install, sizes = taken.get("install"), taken.get("sizes")
    space = []
    if install and install.get("places") is not None:
        space.append("%s after the setup script" % _size(install["places_bytes"]))
    if sizes:
        space.append("%s when the sizes were taken, %s" % (_size(sizes["places_bytes"]), _date(sizes)))
    how = "not measured"
    if install:
        how = "%s, `%s`, exit status %d; the used space on the volume grew by %s" % (
            _date(install), install["command"], install["exit_status"], _size(install["volume_grew_bytes"]))
    _say("| Host installation | %s | %s | %s |" % ("; ".join(space) or "not measured",
                                                  _duration(install["seconds"]) if install else "not measured", how))
    for place in (sizes or install or {}).get("places") or []:
        _say("| of that: %s | %s | | %s |" % (place["what"], _size(place["bytes"]),
                                              place.get("unavailable") or _date(sizes or install)))
    each = (taken.get("build_each") or {}).get("builds") or {}
    by_name = {target["target"]: target for target in (sizes or {}).get("targets") or []}
    for name in sorted(set(each) | set(by_name)):
        build, target = each.get(name), by_name.get(name)
        how = []
        if build:
            how.append("%s, `%s` in an emptied engine, exit status %d, %d steps from the cache" % (
                _date(taken["build_each"]), build["command"], build["exit_status"], build["steps_from_cache"]))
        if target:
            how.append(target["how"])
        _say("| Target: %s | %s | %s | %s |" % (name, _size(target["bytes"]) if target else "not measured",
                                                _duration(build["seconds"]) if build else "not measured",
                                                "; ".join(how)))
    together = taken.get("build_together")
    _say("| All targets, one after the other in an emptied engine | | %s | %s |" % (
        _duration(together["seconds"]) if together else "not measured",
        "%s: %s" % (_date(together), ", then ".join("%s %s" % (build["target"], _duration(build["seconds"]))
                                                    for build in together["builds"])) if together else ""))
    performance = taken.get("performance")
    for mode, runs in ((performance or {}).get("modes") or {}).items():
        seconds = [value for run in runs.values() for value in run["run_seconds"] if value]
        _say("| Performance evaluation: %s | | %s for the %d recorded runs | %s, `--repeat %d`; "
             "`evaluation/footprint.py times` has the median of each workload |" % (
                 mode, _duration(sum(seconds)), len(seconds), _date(performance), performance["repeat"]))
    if not performance:
        _say("| Performance evaluation | | not measured | |")
    verify = taken.get("verify")
    if verify:
        _say("\nVerified afterwards (%s): %s." % (_date(verify), ", ".join(
            "%d %s" % (count, status) for status, count in sorted(verify["checks"].items()))))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     epilog="The stages and what each does: see the top of this file.")
    commands = parser.add_subparsers(dest="command", required=True)
    runs = commands.add_parser("run", help="measure this host")
    runs.add_argument("--stages", metavar="LIST", help="the stages to run, separated by commas, of: %s (default: "
                      "all but install)" % ", ".join(STAGES))
    runs.add_argument("--install", action="store_true", help="also measure the installation: remove it, and time "
                      "the setup script")
    runs.add_argument("--yes", action="store_true", help="do not ask before removing anything")
    runs.add_argument("--dry-run", action="store_true", help="say what would be run; run, remove and record nothing")
    runs.add_argument("--repeat", type=int, default=3, metavar="N", help="runs of each workload in each mode "
                      "(default: 3, which the procedures ask for)")
    runs.add_argument("--mute", action="store_true", help="start the emulator muted for the performance runs")
    runs.add_argument("--no-arm-targets", action="store_true", help="leave the simulated ARM64 and ARM32 targets "
                      "out, on a host that is not set up for them")
    runs.add_argument("--keep-downloads", action="store_true", help="install: leave the downloads the tools kept, "
                      "so that the time is of an installation that fetches less")
    runs.set_defaults(function=run)
    shown = commands.add_parser("table", help="print this host's values as rows for evaluation/footprint.md")
    shown.add_argument("--file", metavar="PATH", help="another host's record (default: this host's)")
    shown.set_defaults(function=table)
    args = parser.parse_args()
    return args.function(args)


if __name__ == "__main__":
    sys.exit(main())
