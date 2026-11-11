"""Performance result records.

Every record names the environment it was measured in: host, host CPU
architecture, emulator mode, client OS image and workload version.
"""
import datetime
import json

from . import catalog
from .errors import EmuError
from .paths import RESULTS_DIR

SCHEMA_VERSION = 1
IDENTITY_FIELDS = (
    ("host", "os"), ("host", "os_version"), ("host", "arch"), ("host", "cpu_model"),
    ("emulator", "mode"), ("emulator", "variant"), ("emulator", "guest_arch"), ("emulator", "runtime"),
    ("image", "name"), ("image", "version"), ("image", "source"), ("image", "definition_sha256"),
    ("workload", "id"), ("workload", "version"),
)


def build(outcome, opts):
    declared = catalog.workload(opts.workload)
    reported = outcome.workload or {}
    if declared and reported.get("version") and reported["version"] != declared["version"]:
        raise EmuError("workload %s reports version %s but evaluation/workloads.json declares %s"
                       % (opts.workload, reported["version"], declared["version"]))
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": outcome.run_id,
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": outcome.environment["host"],
        "emulator": outcome.environment["emulator"],
        "image": dict(outcome.environment["image"], reported_by_target=(outcome.ready or {}).get("image")),
        "target": {key: value for key, value in (outcome.ready or {}).items() if key != "image"},
        "workload": dict(reported, id=opts.workload, version=reported.get("version") or (declared or {}).get("version"),
                         arguments=opts.args),
        "drivers": outcome.environment.get("drivers"),
        "launcher_revision": outcome.environment.get("launcher_revision"),
        "boot_seconds": outcome.boot_seconds,
        "duration_seconds": round(outcome.duration_seconds, 3) if outcome.duration_seconds else None,
        "exit_code": outcome.exit_code,
        "results": outcome.results,
    }
    return record


def missing_identity(record):
    """Identity fields a record lacks; empty when it is fully identified."""
    missing = []
    for section, field in IDENTITY_FIELDS:
        if not (record.get(section) or {}).get(field):
            missing.append("%s.%s" % (section, field))
    return missing


def write(record):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    name = "%s_%s_%s_%s.json" % (record["run_id"], record["host"]["id"], record["emulator"]["variant"],
                                 record["workload"]["id"])
    path = RESULTS_DIR / name
    with open(path, "w") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    return path


def load_all():
    records = []
    for path in sorted(RESULTS_DIR.glob("*.json")):
        with open(path) as handle:
            records.append((path, json.load(handle)))
    return records
