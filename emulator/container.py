"""Container mode: the target OS userland on a container runtime."""
import json
import subprocess

from . import host
from .errors import EmuError


class Runtime:
    """A Docker-compatible container CLI (docker or podman)."""

    def __init__(self, name, cli):
        self.name = name
        self.cli = cli
        self._version = None

    def run(self, *args, timeout=120):
        return subprocess.run([self.cli] + list(args), env=host.tool_env(), capture_output=True, text=True,
                              timeout=timeout)

    def engine_ok(self):
        try:
            return self.run("info", timeout=60).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def version(self):
        if self._version is None:
            done = self.run("version", "--format", "{{json .}}")
            text = "%s (unknown version)" % self.name
            try:
                data = json.loads(done.stdout)
                server = data.get("Server") or {}
                client = data.get("Client") or {}
                text = "%s client %s, engine %s" % (self.name, client.get("Version", "?"),
                                                    server.get("Version") or client.get("Version", "?"))
            except ValueError:
                pass
            self._version = text
        return self._version

    def engine_info(self):
        """Resources of the engine, which bound what a container can use."""
        done = self.run("info", "--format", "{{json .}}")
        try:
            data = json.loads(done.stdout)
        except ValueError:
            return {}
        if self.name == "podman":
            info = data.get("host", {})
            return {"cpus": info.get("cpus"), "memory_bytes": info.get("memTotal"),
                    "kernel": info.get("kernel"), "os": (info.get("distribution") or {}).get("distribution")}
        return {"cpus": data.get("NCPU"), "memory_bytes": data.get("MemTotal"),
                "kernel": data.get("KernelVersion"), "os": data.get("OperatingSystem"),
                "storage_driver": data.get("Driver")}

    def image_id(self, tag):
        done = self.run("image", "inspect", "--format", "{{.Id}}", tag)
        return done.stdout.strip() if done.returncode == 0 else None

    def host_address(self):
        """Name under which a container reaches services on the host."""
        return "host.containers.internal" if self.name == "podman" else "host.docker.internal"


def detect(start_engine=True):
    """Find a container runtime whose engine answers; start one if we can."""
    found = []
    for name in ("docker", "podman"):
        cli = host.find_tool(name)
        if cli:
            runtime = Runtime(name, cli)
            if runtime.engine_ok():
                return runtime
            found.append(runtime)
    if not found:
        raise EmuError("no container runtime found (docker or podman)", hint=host.SETUP_HINT)
    if start_engine and _start_engine(found[0]) and found[0].engine_ok():
        return found[0]
    raise EmuError("the %s engine is not running" % found[0].name, hint=host.SETUP_HINT)


def _start_engine(runtime):
    """Start a stopped local engine: Colima on macOS, the podman machine."""
    command = None
    if runtime.name == "docker" and host.host_os() == "macos" and host.find_tool("colima"):
        command = [host.find_tool("colima"), "start"]
    elif runtime.name == "podman" and host.host_os() != "linux":
        command = [runtime.cli, "machine", "start"]
    if not command:
        return False
    print("emu: starting the container engine (%s)" % " ".join(command[-2:]), flush=True)
    return subprocess.run(command, env=host.tool_env()).returncode == 0


def run_command(runtime, tag, platform, workload, args, cpus, memory_mb, env, interactive, tty, extra_args, name):
    command = [runtime.cli, "run", "--rm", "--init", "--name", name, "--hostname", "emu-target",
               "--platform", platform, "--memory", "%dm" % memory_mb, "--volume", "/data"]
    engine_cpus = runtime.engine_info().get("cpus") or 0
    if engine_cpus >= cpus:
        # Pin to whole CPUs so the target sees exactly this many, as a VM does.
        command += ["--cpuset-cpus", "0-%d" % (cpus - 1)]
    else:
        command += ["--cpus", str(cpus)]
    if interactive:
        command.append("--interactive")
    if tty:
        command.append("--tty")
    if runtime.name == "docker" and host.host_os() == "linux":
        # Docker Desktop and Colima define this name themselves.
        command += ["--add-host", "host.docker.internal:host-gateway"]
    for key, value in sorted(env.items()):
        command += ["--env", "%s=%s" % (key, value)]
    return command + list(extra_args) + [tag, workload] + list(args)
