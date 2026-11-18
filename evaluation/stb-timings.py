#!/usr/bin/env python3
"""Times the STB simulator from the host: how fast it starts and answers its
keys, and what the performance workloads report when they are started from
its user interface.

    python3 evaluation/stb-timings.py run --mode container
    python3 evaluation/stb-timings.py run --mode vm --arch arm32
    python3 evaluation/stb-timings.py table

`run` starts the stb-simulator workload with the launcher's display window,
as `./emu run --workload stb-simulator` does, and operates it with remote
control keys typed into that window, as the launcher's checks do
(emulator/verify.py). Every time is taken on the host's clock, from the
moment a key is given to the window:

  reported   until the line the user interface prints for what the key
             brought about (EMU-STB) has arrived at the launcher
  seen       until the launcher's window has received a changed picture of
             the display (menus), or a picture with the block that names the
             channel's video codec (channels)

Then it starts each performance workload from the user interface, in full,
several times, and keeps what each reported; and it runs each of them as the
launcher does, as often, with the display in the launcher's window as the
simulator has it, to have results taken under the same conditions beside
them. What was observed is written to evaluation/stb-timings/HOST_VARIANT.json;
`table` prints those files as tables, with the results recorded in
evaluation/results (taken without a window) beside the others.

These are findings about the simulator, taken with a method of this
script's own. They are not results of the performance evaluation, and
nothing is written to evaluation/results. See
evaluation/procedures.md#stb-simulator.
"""
import argparse
import datetime
import glob
import json
import os
import statistics
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evaluation", "stb-timings")
sys.dont_write_bytecode = True
sys.path.insert(0, ROOT)

from emulator import catalog, drivers as driver_features, graphics, host, imagefile, verify      # noqa: E402
from emulator.run import RunOptions, launch                                                       # noqa: E402

# What a result is known by, and what is kept of it.
IDENTITY = ("test", "case", "technology", "resolution")
KEPT = ("area",) + IDENTITY + ("value", "unit", "unavailable")
VARIANTS = (("container", "Container"), ("vm-native", "VM, host-native"), ("vm-arm64", "VM, ARM64"),
            ("vm-arm32", "VM, ARM32"))
CODECS = ((1, "MPEG-2"), (2, "AVC"), (3, "HEVC"))


# ---------------------------------------------------------------------- run ---

def run(args):
    width, height = graphics.resolution(args.resolution)
    slow = args.arch != "native"
    only = [name for name in args.only.split(",") if name]

    class Bench(verify._Stb):
        """The checks' way of operating the simulator, with a clock."""

        limit = 600 if slow else 60            # seconds a key may take to bring something about
        quiet = 2.0 if slow else 0.4           # seconds without a new picture before a key is timed

        def updates(self):
            return self.viewer.ask(do="state")["updates"]

        def settle(self):
            """Wait until the window gets no new pictures; returns their count."""
            last, since, end = self.updates(), time.monotonic(), time.monotonic() + 15 * self.quiet + 10
            while time.monotonic() < end:
                time.sleep(0.05)
                now = self.updates()
                if now != last:
                    last, since = now, time.monotonic()
                elif time.monotonic() - since >= self.quiet:
                    break
            return last

        def timed(self, key, wanted, what, idle=0):
            before = self.settle()
            if idle:
                # A screen that has shown nothing new for this long.
                time.sleep(idle)
                before = self.updates()
            start = self.mark()
            began = time.monotonic()
            self.press(key)
            event = seen_at = None
            while time.monotonic() < began + self.limit:
                if event is None:
                    with self.seen["lock"]:
                        event = next((e for e in self.seen["events"][start:] if wanted(e)), None)
                if seen_at is None and self.viewer.ask(do="state")["updates"] > before:
                    seen_at = time.monotonic()
                if event is not None and seen_at is not None:
                    break
                time.sleep(0.002)
            if event is None:
                raise verify.CheckFailed("after %s, %s was not reported within %d s" % (key, what, self.limit))
            return {"key": key, "reported": round(event["_at"] - began, 4),
                    "seen": None if seen_at is None else round(seen_at - began, 4)}

        def first_key(self, since):
            """How long after `since` the user interface takes keys: the red
            key, which has no function there and is reported, is pressed
            until it is."""
            start = self.mark()
            found = None
            for _ in range(900):
                self.press("red")
                end = time.monotonic() + (1.0 if slow else 0.05)
                while found is None and time.monotonic() < end:
                    with self.seen["lock"]:
                        found = next((e for e in self.seen["events"][start:] if e.get("event") == "key"), None)
                    time.sleep(0.005)
                if found is not None:
                    break
            if found is None:
                raise verify.CheckFailed("the user interface takes no keys")
            # The presses that were on their way arrive too; wait them out.
            count = -1
            while count != self.mark():
                count = self.mark()
                time.sleep(3.0 if slow else 1.0)
            return round(found["_at"] - since, 3)

        def capture(self, name):
            if args.captures:
                os.makedirs(args.captures, exist_ok=True)
                self.viewer.ask(do="save-display", path=os.path.join(args.captures, "%s-%s-%s.png" % (
                    args.mode, args.arch, name)))

        # ----------------------------------------------------------- menus ---

        def menus(self):
            found = {"moves": [], "idle": [], "open": [], "back": []}
            self.to_home()
            self.select(self.home_now(), "channels")
            self.capture("home")
            focus = lambda name: (lambda e: e.get("event") == "focus" and e.get("focus") == name)
            count = 0

            def move(idle=0):
                nonlocal count
                key, target = ("down", "apps") if count % 2 == 0 else ("up", "channels")
                count += 1
                return self.timed(key, focus(target), "the selection moving to %s" % target, idle)

            for _ in range(args.moves):
                found["moves"].append(move())
            # The same after the screen has shown nothing new for a while.
            for idle in [float(text) for text in args.idle.split(",") if text]:
                for _ in range(args.idle_moves):
                    found["idle"].append(dict(move(idle), idle=idle))
            self.select(self.home_now(), "channels")
            for _ in range(args.screens):
                found["open"].append(self.timed("ok", self.screen("channels"), "the channel list"))
                found["back"].append(self.timed("back", self.screen("home"), "the home screen"))
            return found

        # -------------------------------------------------------- channels ---

        def marker_shown(self, marker):
            """Whether the display, as the window has it, shows a reference
            stream with this block at the top centre."""
            path = os.path.join(self.directory, "now.ppm")
            if not self.viewer.ask(do="save-display", path=path).get("saved"):
                return False
            image = imagefile.load(path)
            if (image.width, image.height) != (self.width, self.height):
                return False
            block = self.height // 12
            close = lambda a, b: all(abs(x - y) <= graphics.VIDEO_COLOR_TOLERANCE for x, y in zip(a, b))
            return close(image.pixel(self.width // 2, block // 2), marker) and \
                close(image.pixel(block // 2, block // 2), graphics.CORNER_COLORS[0])

        def zap(self, key, number):
            """Press a key that brings a channel about, and time it."""
            marker = tuple(next(c["marker"] for c in self.seen["described"]["channels"] if c["number"] == number))
            start = self.mark()
            began = time.monotonic()
            self.press(key)
            got = {"key": key, "channel": number, "tuning": None, "playing": None, "picture": None}
            while time.monotonic() < began + self.patience:
                with self.seen["lock"]:
                    events = list(self.seen["events"][start:])
                for event in events:
                    if event.get("event") != "channel" or event.get("number") != number:
                        continue
                    state = event.get("state")
                    if state in ("tuning", "playing") and got[state] is None:
                        got[state] = round(event["_at"] - began, 4)
                    if state == "error":
                        got["error"] = event.get("reason")
                if got["picture"] is None and self.marker_shown(marker):
                    got["picture"] = round(time.monotonic() - began, 4)
                if "error" in got or (got["playing"] is not None and got["picture"] is not None):
                    break
                time.sleep(0.2 if slow else 0.02)
            return got

        def channels(self):
            found = {"first": None, "changes": [], "pictures": []}
            self.to_home()
            listed = self.open(self.home_now(), "channels", "channels")
            numbers = [c["number"] for c in self.seen["described"]["channels"]]
            now = int(listed["focus"])
            found["first"] = self.zap("ok", now)
            self.capture("channel-%d" % now)
            for _ in range(args.zaps):
                for _ in numbers:
                    now = numbers[(numbers.index(now) + 1) % len(numbers)]
                    found["changes"].append(self.zap("up", now))
            # How many pictures of each channel reach the window in a second.
            for _ in numbers:
                now = numbers[(numbers.index(now) + 1) % len(numbers)]
                change = self.zap("up", now)
                found["changes"].append(change)
                if change.get("picture") is None:
                    continue
                time.sleep(2.0)
                first, began = self.updates(), time.monotonic()
                time.sleep(args.rate_seconds)
                last, ended = self.updates(), time.monotonic()
                found["pictures"].append({"channel": now, "seconds": round(ended - began, 2), "pictures": last - first,
                                          "per_second": round((last - first) / (ended - began), 2)})
            self.press_for("back", self.screen("channels"), "the channel list again")
            return found

        # ------------------------------------------------------------- vod ---

        def vod(self):
            found = {"start": [], "leave": [], "titles": []}
            titles_shown = lambda e: e.get("event") == "vod" and e.get("state") == "titles"
            self.to_home()
            apps = self.open(self.home_now(), "apps", "apps")
            self.select(apps, "vod")
            for _ in range(args.apps):
                found["start"].append(self.timed("ok", titles_shown, "the application's titles"))
                found["leave"].append(self.timed("back", self.screen("apps"), "the app launcher"))
            self.press_for("ok", titles_shown, "the application's titles")

            def choose(title):
                shown = self.last(titles_shown)
                items, focus = shown["titles"], shown["focus"]
                steps = items.index(title) - items.index(focus)
                for _ in range(abs(steps)):
                    focus = items[items.index(focus) + (1 if steps > 0 else -1)]
                    self.press_for("down" if steps > 0 else "up",
                                   lambda e, focus=focus: titles_shown(e) and e.get("focus") == focus,
                                   "the selection moving to %r" % focus)

            def at_titles():
                """A title that ends by itself returns to the titles, where
                BACK leaves the application: when that has happened, the
                application is started again."""
                time.sleep(3.0 if slow else 0.5)
                place = self.last(lambda e: e.get("event") == "screen" or titles_shown(e))
                if place.get("event") == "screen":
                    self.press_for("ok", titles_shown, "the application's titles")
                    return False
                return True

            def play(title, watch):
                """Play a title for `watch` seconds after it started playing."""
                at_titles()
                choose(title)
                start = self.mark()
                began = time.monotonic()
                self.press("ok")
                got = {"title": title, "watched_seconds": watch, "stream": None, "playing": None,
                       "representations": [], "offered": None}
                events = []
                while time.monotonic() < began + self.patience:
                    with self.seen["lock"]:
                        events = [e for e in self.seen["events"][start:] if e.get("event") == "vod"
                                  and e.get("title") == title]
                    if not events and "pressed_again" not in got and time.monotonic() - began > self.limit / 5:
                        # Nothing came of the key: it is pressed once more, and that is kept.
                        got["pressed_again"] = round(time.monotonic() - began, 1)
                        start = self.mark()
                        began = time.monotonic()
                        self.press("ok")
                    first = next((e for e in events if e["state"] == "playing"), None)
                    if any(e["state"] in ("error", "ended", "stopped") for e in events):
                        break
                    if first is not None and time.monotonic() - first["_at"] >= watch:
                        break
                    time.sleep(0.1)
                for event in events:
                    at = round(event["_at"] - began, 3)
                    state = event["state"]
                    if state == "stream" and got["stream"] is None:
                        got["stream"] = at
                        got["offered"] = ["%sx%s at %.2f Mbit/s" % (r.get("width"), r.get("height"),
                                                                     (r.get("bandwidth") or 0) / 1e6)
                                          for r in event.get("representations") or []]
                    elif state == "playing" and got["playing"] is None:
                        got["playing"] = at
                    elif state == "representation":
                        shown = event["representation"]
                        got["representations"].append({"at": at, "media_time": event.get("time"),
                                                       "size": "%sx%s" % (shown.get("width"), shown.get("height")),
                                                       "mbit": round((shown.get("bandwidth") or 0) / 1e6, 2)})
                    elif state == "progress":
                        got["progress"] = {"at": at, "media_time": event.get("time"), "frames": event.get("frames"),
                                           "dropped": event.get("dropped"), "video": event.get("video")}
                    elif state == "error":
                        got["error"] = event.get("reason")
                if "error" in got:
                    self.press("ok")            # the message goes; the titles are underneath
                elif not any(e["state"] in ("ended", "stopped") for e in events):
                    self.capture(title)
                    again = self.mark()
                    self.press("back")
                    if self.wait(again, lambda e: titles_shown(e) or e.get("event") == "screen") is None:
                        raise verify.CheckFailed("after BACK, %s did not return to the titles" % title)
                return got

            for title, watch in (("test-pattern", 12), ("big-buck-bunny", 20)):
                for _ in range(args.titles):
                    found["titles"].append(play(title, watch * (3 if slow else 1)))
                    self.seen["parts"]["vod"] = found           # kept, should a later title fail
            if at_titles():
                self.press_for("back", self.screen("apps"), "the simulator's app launcher again")
            return found

        # ------------------------------------------------------- workloads ---

        def workloads(self):
            found = []
            self.to_home()
            listed = self.open(self.home_now(), "performance", "performance")
            for number in range(args.rounds):
                for name in listed["items"]:
                    shown = self.last(self.screen("performance"))
                    moved = self.last(lambda e: e.get("event") in ("focus", "screen") and e.get("screen") == "performance")
                    self.select(dict(shown, focus=(moved or shown)["focus"]), name)
                    with self.seen["lock"]:
                        first = len(self.seen["results"])
                    start = self.mark()
                    began = time.monotonic()
                    self.press("ok")
                    finished = self.wait(start, lambda e: e.get("event") == "workload" and e.get("id") == name
                                         and e.get("state") == "finished", 3600)
                    if finished is None:
                        raise verify.CheckFailed("the %s workload did not finish" % name)
                    results = self.wait(start, self.screen("results"))
                    with self.seen["lock"]:
                        reported = self.seen["results"][first:]
                    run = {"round": number + 1, "id": name, "status": finished.get("status"),
                           "version": next((r.get("workload_version") for r in reported), None),
                           "workload_seconds": finished.get("seconds"),
                           "key_to_finished": round(finished["_at"] - began, 2),
                           "finished_to_results_screen": None if results is None else round(results["_at"] - finished["_at"], 2),
                           "results": [{key: result.get(key) for key in KEPT} for result in reported]}
                    found.append(run)
                    self.seen["parts"]["workloads"] = found         # kept, should a later run fail
                    if results is None:
                        raise verify.CheckFailed("after %s the user interface did not show its results" % name)
                    run["results_screen_to_keys"] = self.first_key(results["_at"])
                    if number == 0:
                        self.capture("results-" + name)
                    self.press_for("back", self.screen("performance"), "the list of performance tests again")
            return found

    log = open(args.log, "a") if args.log else None

    def session(number):
        """One start of the simulator; the first one does everything."""
        seen = {"events": [], "results": [], "lock": threading.Lock(), "ready": threading.Event(), "described": None,
                "parts": {}}

        def on_line(line):
            now = time.monotonic()
            for marker in ("EMU-STB: ", "EMU-WORKLOAD: ", "EMU-RESULT: "):
                start = line.find(marker)
                if start < 0:
                    continue
                try:
                    data = json.loads(line[start + len(marker):])
                except ValueError:
                    return
                if not isinstance(data, dict):
                    return
                data["_at"] = now
                if log:
                    log.write("%9.3f %s%s\n" % (now - seen["launched"], marker, line[start + len(marker):][:400]))
                    log.flush()
                if marker == "EMU-WORKLOAD: ":
                    if data.get("id") == "stb-simulator":
                        seen["described"] = data
                elif marker == "EMU-RESULT: ":
                    with seen["lock"]:
                        seen["results"].append(data)
                else:
                    with seen["lock"]:
                        seen["events"].append(data)
                    if data.get("event") == "screen" and data.get("screen") == "home":
                        seen["ready"].set()
                return

        with tempfile.TemporaryDirectory(prefix="emu-stb-timings-") as directory:
            def drive(viewer):
                def work():
                    bench = Bench(viewer, seen, width, height, directory, slow=slow)
                    try:
                        if not seen["ready"].wait(3600):
                            seen["error"] = "the user interface never appeared"
                            viewer.ask(do="quit")
                            return
                        with seen["lock"]:
                            home = next(e for e in seen["events"] if e.get("event") == "screen" and e.get("screen") == "home")
                        described = seen["described"] or {}
                        seen["parts"]["start"] = {
                            "launch_to_home_screen": round(home["_at"] - seen["launched"], 3),
                            "launch_to_workload": round(described["_at"] - seen["launched"], 3) if described else None,
                            "home_screen_to_first_key": bench.first_key(home["_at"])}
                        if number == 0:
                            for name, part in (("menus", bench.menus), ("channels", bench.channels), ("vod", bench.vod),
                                               ("workloads", bench.workloads)):
                                if only and name not in only:
                                    continue
                                began = time.monotonic()
                                try:
                                    seen["parts"][name] = part()
                                except verify.CheckFailed as error:
                                    seen["parts"][name + "-error"] = str(error)
                                except Exception as error:
                                    seen["parts"][name + "-error"] = "%s: %s" % (type(error).__name__, error)
                                print("%s %s: %s done in %.0f s%s" % (
                                    args.mode, args.arch, name, time.monotonic() - began,
                                    " (%s)" % seen["parts"][name + "-error"] if name + "-error" in seen["parts"] else ""),
                                    flush=True)
                        bench.to_home()
                        bench.select(bench.home_now(), "off")
                        seen["off"] = time.monotonic()
                        bench.press("ok")
                    except Exception as error:
                        seen["error"] = "%s: %s" % (type(error).__name__, error)
                        try:
                            viewer.ask(do="quit")
                        except Exception:
                            pass
                threading.Thread(target=work, daemon=True).start()

            opts = RunOptions(mode=args.mode, arch=args.arch, workload="stb-simulator", resolution=args.resolution,
                              window=True, remote_control="keys", drivers=driver_features.parse(["audio=host"]),
                              options={"audio-output": "none"}, on_line=on_line, on_viewer=drive, timeout=8 * 3600,
                              echo=False, quiet_build=True)
            seen["launched"] = time.monotonic()
            outcome = launch(opts)
            ended = time.monotonic()
        start = seen["parts"].pop("start", {})
        start.update(boot_seconds=outcome.boot_seconds,
                     switch_off_to_end=round(ended - seen["off"], 3) if "off" in seen else None,
                     exit_code=outcome.exit_code, error=seen.get("error"))
        return seen, outcome, start

    def direct():
        """Each performance workload as the launcher runs it, with the
        display in the launcher's window as the simulator has it."""
        found = []
        names = [w["id"] for w in catalog.workloads()["workloads"] if w.get("kind") == "performance"
                 and w.get("status") == "implemented"]
        for number in range(args.rounds):
            for name in names:
                outcome = launch(RunOptions(
                    mode=args.mode, arch=args.arch, workload=name, resolution=args.resolution, window=True,
                    remote_control="keys", drivers=driver_features.parse(["audio=host"]),
                    options={"audio-output": "none"}, timeout=2 * 3600, echo=False, quiet_build=True))
                found.append({"round": number + 1, "id": name, "status": outcome.exit_code,
                              "version": (outcome.workload or {}).get("version"), "boot_seconds": outcome.boot_seconds,
                              "duration_seconds": round(outcome.duration_seconds or 0, 1),
                              "results": [{key: result.get(key) for key in KEPT} for result in outcome.results]})
                print("%s %s: %s as the launcher runs it, with the window: status %s, %.0f s" % (
                    args.mode, args.arch, name, outcome.exit_code, outcome.duration_seconds or 0), flush=True)
        return found

    report = {"taken": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "counts": {name: getattr(args, name) for name in ("starts", "moves", "idle", "idle_moves", "screens", "zaps",
                                                                "rate_seconds", "apps", "titles", "rounds", "only")},
              "starts": []}
    path = None
    for number in range(max(1, args.starts)):
        seen, outcome, start = session(number)
        report["starts"].append(start)
        environment = outcome.environment
        if number == 0:
            report.update(
                host=environment["host"], emulator=environment["emulator"], image=environment["image"],
                drivers=environment.get("drivers"), launcher_revision=environment.get("launcher_revision"),
                simulator={key: value for key, value in (seen["described"] or {}).items() if key != "_at"},
                notes=outcome.notes, parts=seen["parts"])
        os.makedirs(OUT, exist_ok=True)
        path = _timings_path(environment["host"], environment["emulator"]["variant"])
        if not only:
            with open(path, "w") as handle:
                json.dump(report, handle, indent=1)
                handle.write("\n")
        print("%s %s: start %d: %s" % (args.mode, args.arch, number + 1, json.dumps(start)), flush=True)
    if not only or "direct" in only:
        report["parts"]["direct"] = direct()
        if not only:
            with open(path, "w") as handle:
                json.dump(report, handle, indent=1)
                handle.write("\n")
    if only:
        print(json.dumps(report["parts"], indent=1))
        print("a part of the run only (--only): nothing was written")
    else:
        print("written: %s" % os.path.relpath(path, ROOT))
    return 0 if all(start["exit_code"] == 0 and not start["error"] for start in report["starts"]) else 1


# -------------------------------------------------------------------- table ---

def seconds(values, digits=None):
    values = [value for value in values if value is not None]
    if not values:
        return "not measured"
    middle = statistics.median(values)
    if digits is None:
        digits = 3 if middle < 0.1 else (2 if middle < 10 else 1)
    form = "%%.%df" % digits
    if len(values) == 1:
        return (form + " s (1 time)") % middle
    return (form + " s (" + form + " to " + form + ", %d times)") % (middle, min(values), max(values), len(values))


def _timings_path(described, variant):
    """One file per host, machine and mode."""
    return os.path.join(OUT, "%s_%s_%s.json" % (described["id"], host.machine_of(described), variant))


def table(args):
    # A host id, or a host id and a machine id as HOST@MACHINE.
    host_id, _, machine = (args.host or host.host_key()).partition("@")
    data = {}
    for variant, _ in VARIANTS:
        found = sorted(glob.glob(os.path.join(OUT, "%s_%s_%s.json" % (host_id, machine or "*", variant))))
        if len(found) > 1:
            print("%s has timings of more than one machine; name one as %s@MACHINE: %s" % (
                host_id, host_id, ", ".join(os.path.basename(path) for path in found)))
            return 1
        if found:
            with open(found[0]) as handle:
                data[variant] = json.load(handle)
    if not data:
        print("no timings for %s in %s" % (args.host or host.host_key(), os.path.relpath(OUT, ROOT)))
        return 1
    machine = host.machine_of(next(iter(data.values()))["host"])

    def row(label, cell):
        cells = []
        for variant, _ in VARIANTS:
            if variant not in data:
                cells.append("not run")
                continue
            try:
                cells.append(cell(data[variant]))
            except (KeyError, TypeError, IndexError):
                cells.append("not measured")
        print("| %s | %s |" % (label, " | ".join(cells)))

    part = lambda found, name: found["parts"][name]
    of = lambda name, kind, field: (lambda d: seconds([m[field] for m in part(d, name)[kind]]))
    print("Host %s. Median (smallest to largest, how many times)." % host_id)
    print()
    print("| What | %s |" % " | ".join(title for _, title in VARIANTS))
    print("|---|%s" % ("---|" * len(VARIANTS)))
    row("Image, and when taken", lambda d: "%s, %s" % (d["image"]["version"], d["taken"][:10]))
    row("Launch to the home screen", lambda d: seconds([s.get("launch_to_home_screen") for s in d["starts"]]))
    row("of that, until the target has started the workload", lambda d: seconds([s.get("launch_to_workload") for s in d["starts"]]))
    row("Home screen to the first key taken", lambda d: seconds([s.get("home_screen_to_first_key") for s in d["starts"]]))
    row("Switch off to the emulator ended", lambda d: seconds([s.get("switch_off_to_end") for s in d["starts"]]))
    row("Move the selection: reported", of("menus", "moves", "reported"))
    row("Move the selection: seen in the window", of("menus", "moves", "seen"))
    idles = sorted({m["idle"] for d in data.values() for m in (d["parts"].get("menus") or {}).get("idle", [])})
    for idle in idles:
        row("the same after %g s without a new picture" % idle,
            lambda d, idle=idle: seconds([m["seen"] for m in part(d, "menus")["idle"] if m["idle"] == idle]))
    row("Open a screen (OK): reported", of("menus", "open", "reported"))
    row("Open a screen (OK): seen in the window", of("menus", "open", "seen"))
    row("Return (BACK): reported", of("menus", "back", "reported"))
    row("Return (BACK): seen in the window", of("menus", "back", "seen"))
    row("First channel from the list: its picture in the window", lambda d: seconds([part(d, "channels")["first"]["picture"]]))
    row("Channel change (Up): reported as playing", of("channels", "changes", "playing"))
    row("Channel change (Up): its picture in the window", of("channels", "changes", "picture"))
    for number, codec in CODECS:
        row("of those, to channel %d (%s)" % (number, codec), lambda d, number=number: seconds(
            [c["picture"] for c in part(d, "channels")["changes"] if c["channel"] == number]))
    for number, codec in CODECS:
        row("Pictures a second in the window, channel %d (%s)" % (number, codec), lambda d, number=number: ", ".join(
            "%.1f" % p["per_second"] for p in part(d, "channels")["pictures"] if p["channel"] == number) or "not measured")
    row("Start the video on demand application: its titles reported", of("vod", "start", "reported"))
    row("Start the video on demand application: seen in the window", of("vod", "start", "seen"))
    row("Leave it (BACK): the app launcher reported", of("vod", "leave", "reported"))

    def titles(d, title):
        return [played for played in part(d, "vod")["titles"] if played["title"] == title]

    def last_shown(d, title):
        cells = []
        for played in titles(d, title):
            if played.get("error"):
                cells.append("refused (%s)" % played["error"])
            elif played["representations"]:
                last = played["representations"][-1]
                cells.append("%s after %.1f s" % (last["size"], last["at"]))
            else:
                cells.append("none reported")
        return "; ".join(cells) or "not measured"

    def counted(d, title):
        return "; ".join("%s frames, %s dropped, at %s s of the title" % (
            played["progress"]["frames"], played["progress"]["dropped"], played["progress"]["media_time"])
            for played in titles(d, title) if played.get("progress")) or "not reported"

    for title, name in (("test-pattern", "Test title"), ("big-buck-bunny", "Big Buck Bunny")):
        row("%s: OK to the stream's description read" % name, lambda d, t=title: seconds([p["stream"] for p in titles(d, t)]))
        row("%s: OK to reported as playing" % name, lambda d, t=title: seconds([p["playing"] for p in titles(d, t)]))
        row("%s: the last representation shown, and when" % name, lambda d, t=title: last_shown(d, t))
        row("%s: the browser's last count of frames" % name, lambda d, t=title: counted(d, t))
    took = lambda d, field: seconds([w.get(field) for w in part(d, "workloads") if w["id"] != "bench"])
    row("After a workload that took the display: the results screen", lambda d: took(d, "finished_to_results_screen"))
    row("and from there to the first key taken", lambda d: took(d, "results_screen_to_keys"))
    for variant, title in VARIANTS:
        errors = ["%s: %s" % (name[:-6], text) for name, text in (data.get(variant) or {"parts": {}})["parts"].items()
                  if name.endswith("-error")]
        errors += ["start %d: %s" % (index + 1, start["error"]) for index, start in
                   enumerate((data.get(variant) or {"starts": []})["starts"]) if start.get("error")]
        if errors:
            print()
            print("%s, not completed: %s" % (title, "; ".join(errors)))

    # The workloads' results: from the user interface, as the launcher runs
    # them with the window, and as recorded (without a window).
    recorded = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "evaluation", "results", "*_%s_*.json" % host_id))):
        with open(path) as handle:
            record = json.load(handle)
        if host.machine_of(record["host"]) != machine:
            continue
        recorded.setdefault((record["emulator"]["variant"], record["workload"]["id"]), []).append(record)
    identity = lambda result: tuple(result.get(key) for key in IDENTITY)

    def medians(found):
        values = {}
        for one in found:
            for result in one["results"]:
                if result.get("value") is not None:
                    values.setdefault(identity(result), []).append(result["value"])
        return {key: statistics.median(numbers) for key, numbers in values.items()}

    def compared(first, second, label, apart):
        """How the results of two sets of runs lie to each other."""
        ratios = []
        for key in sorted(set(first) & set(second), key=str):
            a, b = first[key], second[key]
            if a == b:
                ratios.append(1.0)
            elif not a or not b:
                apart.append(label + (key, a, b, None))
            else:
                ratios.append(a / b)
                if abs(a / b - 1) > 0.10:
                    apart.append(label + (key, a, b, a / b))
        if not ratios:
            return "nothing to compare"
        return "%d results: %d within 5%%, %d within 10%%, ratios %.2f to %.2f" % (
            len(ratios), sum(1 for ratio in ratios if abs(ratio - 1) <= 0.05),
            sum(1 for ratio in ratios if abs(ratio - 1) <= 0.10), min(ratios), max(ratios))

    print()
    print("| Workload | Mode | From the user interface | As the launcher runs it, with the window | Recorded, without a window "
          "| User interface against launcher with the window | Launcher with the window against recorded |")
    print("|---|---|---|---|---|---|---|")
    apart_ui, apart_window = [], []
    for variant, title in VARIANTS:
        parts = (data.get(variant) or {"parts": {}})["parts"]
        runs, direct = parts.get("workloads") or [], parts.get("direct") or []
        for workload in sorted({run["id"] for run in runs + direct}):
            mine = [run for run in runs if run["id"] == workload]
            same = [run for run in direct if run["id"] == workload]
            version = (mine or same)[0].get("version")
            theirs = [record for record in recorded.get((variant, workload), [])
                      if record["workload"]["version"] == version
                      and (record["emulator"].get("display") or {}).get("resolution") in (
                          None, data[variant]["simulator"].get("resolution"))]
            status = lambda found: ", ".join(sorted({str(run["status"]) for run in found}))
            print("| %s %s | %s | %s | %s | %s | %s | %s |" % (
                workload, version, title,
                "%d runs, status %s, %s" % (len(mine), status(mine), seconds([run["workload_seconds"] for run in mine], 1))
                if mine else "not run",
                "%d runs, status %s, %s" % (len(same), status(same), seconds(
                    [run["duration_seconds"] - (run.get("boot_seconds") or 0) for run in same], 1)) if same else "not run",
                "%d runs on image %s, %s" % (len(theirs), ", ".join(sorted({r["image"]["version"] for r in theirs})), seconds(
                    [r["duration_seconds"] - (r.get("boot_seconds") or 0) for r in theirs], 1)) if theirs else "none",
                compared(medians(mine), medians(same), (workload, title), apart_ui),
                compared(medians(same), medians(theirs), (workload, title), apart_window)))
    if any(run["status"] != 0 for found in data.values()
           for run in (found["parts"].get("workloads") or []) + (found["parts"].get("direct") or [])):
        print()
        print("A status other than 0: the workload failed, or (None) the emulator ended before the workload "
              "reported how it ended; the results it had reported by then are counted.")
    for apart, what in ((apart_ui, "From the user interface against the launcher with the window"),
                        (apart_window, "The launcher with the window against the recorded results")):
        if apart:
            print()
            print("%s, more than 10%% apart (the two medians, and their ratio):" % what)
            for workload, title, key, a, b, ratio in apart:
                print("- %s, %s, %s: %s, %s%s" % (workload, title, " ".join(str(part) for part in key if part), a, b,
                                                  "" if ratio is None else ", %.2f" % ratio))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.required = True
    one = commands.add_parser("run", help="time the simulator in one mode")
    one.add_argument("--mode", required=True, choices=("container", "vm"))
    one.add_argument("--arch", default="native", choices=("native", "arm64", "arm32"))
    one.add_argument("--resolution", default="1080p")
    one.add_argument("--starts", type=int, default=3, help="times the simulator is started (the first start does the rest)")
    one.add_argument("--moves", type=int, default=20, help="selection moves on the home screen")
    one.add_argument("--idle", default="5,30", help="seconds without a new picture before a move is timed again")
    one.add_argument("--idle-moves", type=int, default=3, help="moves timed after each of those")
    one.add_argument("--screens", type=int, default=5, help="times a screen is opened and left")
    one.add_argument("--zaps", type=int, default=3, help="rounds through the channels")
    one.add_argument("--rate-seconds", type=float, default=10.0, help="how long the pictures of a channel are counted")
    one.add_argument("--apps", type=int, default=3, help="times the video on demand application is started and left")
    one.add_argument("--titles", type=int, default=3, help="times each title is played")
    one.add_argument("--rounds", type=int, default=3,
                     help="times each performance workload is run from the user interface, and as the launcher runs it")
    one.add_argument("--only", default="", help="parts to try, of menus, channels, vod, workloads, direct; nothing is written")
    one.add_argument("--captures", metavar="DIRECTORY", help="save pictures of the display here as it goes")
    one.add_argument("--log", metavar="FILE", help="write what the simulator reports here, with the time of each line")
    shown = commands.add_parser("table", help="print the timings of a host as tables")
    shown.add_argument("--host", help="host id, as in evaluation/matrix.json, or HOST@MACHINE where a host id has "
                       "timings of more than one machine (default: this host on this machine)")
    args = parser.parse_args()
    return run(args) if args.command == "run" else table(args)


if __name__ == "__main__":
    sys.exit(main())
