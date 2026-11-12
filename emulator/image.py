"""The simulated target OS image: its identity, and how it is built.

target/Dockerfile defines the image once. The container runtime builds it for
a target architecture either as a container image (container mode) or as VM
artifacts: an ext4 root filesystem, kernel and initramfs (VM mode).
"""
import datetime
import hashlib
import json
import shutil
import subprocess

from . import host
from .errors import EmuError
from .paths import BUILD_DIR, ROOT, TARGET_DIR

ARCHS = ("x86_64", "arm64", "arm32")
VM_FILES = ("rootfs.img", "vmlinuz", "initrd.img")


def definition():
    with open(TARGET_DIR / "image.json") as handle:
        return json.load(handle)


def _definition_files():
    return sorted(p for p in TARGET_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def definition_sha256():
    """Hash of everything that defines the image (the target/ directory).

    It covers file names and contents only, so every host computes the same
    hash from the same revision. File modes are not part of it: a Windows
    file system has no executable bit, and target/Dockerfile sets the modes
    in the image from the files' contents.
    """
    digest = hashlib.sha256()
    for path in _definition_files():
        relative = path.relative_to(TARGET_DIR).as_posix()
        digest.update(relative.encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def check_definition():
    """Refuse to build from files with Windows line endings: the target's
    scripts would not run, and the definition would hash differently."""
    converted = []
    for path in _definition_files():
        data = path.read_bytes()
        if b"\r\n" in data and b"\0" not in data:       # text files only
            converted.append(path.relative_to(ROOT).as_posix())
    if converted:
        raise EmuError(
            "the image definition has Windows (CRLF) line endings in %d files, such as %s"
            % (len(converted), converted[0]),
            hint="check the files out with LF line endings; .gitattributes asks for them, so a fresh clone has them")


def git_revision():
    """Repository revision, with "-dirty" when the work tree differs from it."""
    git = host.find_tool("git")
    if not git:
        return None
    try:
        commit = subprocess.run([git, "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
        if commit.returncode != 0:
            return None
        status = subprocess.run([git, "-C", str(ROOT), "status", "--porcelain", "--", "target", "emulator"],
                                capture_output=True, text=True, timeout=20)
        return commit.stdout.strip() + ("-dirty" if status.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return None


def arch_info(arch):
    try:
        return definition()["architectures"][arch]
    except KeyError:
        raise EmuError("unknown target architecture: %s" % arch)


def container_tag(arch):
    spec = definition()
    return "%s:%s-%s" % (spec["name"], spec["version"], arch)


def artifact_dir(kind, arch):
    return BUILD_DIR / kind / arch


def load_manifest(kind, arch):
    path = artifact_dir(kind, arch) / "manifest.json"
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def is_current(manifest):
    return bool(manifest) and manifest.get("definition_sha256") == definition_sha256()


def _base_image(spec):
    source = spec["source"]
    if source.get("base_image_digest"):
        return "%s@%s" % (source["base_image"], source["base_image_digest"])
    return source["base_image"]


def _build_command(runtime, arch, stage, tag, definition_hash):
    spec = definition()
    info = arch_info(arch)
    args = {
        "BASE_IMAGE": _base_image(spec),
        "APT_SNAPSHOT": spec["source"].get("apt_snapshot", ""),
        "IMAGE_NAME": spec["name"],
        "IMAGE_VERSION": spec["version"],
        "DEFINITION_SHA256": definition_hash,
        "KERNEL_PACKAGE": info["kernel_package"],
        "FLUTTER_VERSION": spec["source"]["flutter"]["version"],
        "FLUTTER_REVISION": spec["source"]["flutter"]["revision"],
    }
    command = [runtime.cli, "build", "--platform", info["platform"], "--target", stage, "--tag", tag,
               "--file", str(TARGET_DIR / "Dockerfile")]
    for key, value in sorted(args.items()):
        command += ["--build-arg", "%s=%s" % (key, value)]
    return command + [str(TARGET_DIR)]


def _run_build(command, quiet, arch):
    # Building for another CPU architecture runs its binaries under emulation,
    # which the container engine loses when it restarts; setup restores it.
    hint = None
    if arch != host.host_arch():
        hint = "if the build could not run %s programs, %s" % (arch, host.SETUP_HINT)
    # Docker engines before version 23 build with their old builder unless
    # told otherwise, and that one cannot build for another architecture: it
    # reuses a stage it built for the host's. Later engines ignore the setting.
    env = host.tool_env({"DOCKER_BUILDKIT": "1"})
    if quiet:
        done = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if done.returncode != 0:
            raise EmuError("image build failed:\n" + done.stdout[-4000:], hint=hint)
    else:
        print("+ " + " ".join(command), flush=True)
        if subprocess.run(command, env=env).returncode != 0:
            raise EmuError("image build failed", hint=hint)


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(kind, arch, runtime, definition_hash):
    spec = definition()
    return {
        "kind": kind,
        "arch": arch,
        "platform": arch_info(arch)["platform"],
        "name": spec["name"],
        "version": spec["version"],
        "source": spec["source"],
        # The hash the build was started with: the definition may be edited
        # while a long build runs, and the manifest must describe what was built.
        "definition_sha256": definition_hash,
        "build_revision": git_revision(),
        "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "built_with": runtime.version(),
        "built_on": host.host_id(),
    }


def _write_manifest(kind, arch, manifest):
    directory = artifact_dir(kind, arch)
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / "manifest.json", "w") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")


def build_container(runtime, arch, quiet=False):
    """Build the container-mode image; returns its manifest."""
    tag = container_tag(arch)
    definition_hash = definition_sha256()
    _run_build(_build_command(runtime, arch, "target", tag, definition_hash), quiet, arch)
    manifest = _manifest("container", arch, runtime, definition_hash)
    manifest["image_tag"] = tag
    manifest["image_id"] = runtime.image_id(tag)
    _write_manifest("container", arch, manifest)
    return manifest


def build_vm(runtime, arch, quiet=False):
    """Build the VM-mode artifacts into build/vm/ARCH; returns their manifest."""
    tag = "%s-vmimage" % container_tag(arch)
    definition_hash = definition_sha256()
    _run_build(_build_command(runtime, arch, "vmimage", tag, definition_hash), quiet, arch)
    directory = artifact_dir("vm", arch)
    staging = directory.with_name(arch + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    # The artifacts sit in a scratch image; copy them out through a container
    # that is created but never started.
    created = subprocess.run([runtime.cli, "create", "--platform", arch_info(arch)["platform"], tag, "/unused"],
                             env=host.tool_env(), capture_output=True, text=True)
    if created.returncode != 0:
        raise EmuError("could not create a container from %s: %s" % (tag, created.stderr.strip()))
    container = created.stdout.strip().splitlines()[-1]
    try:
        for name in VM_FILES + ("image.json", "kernel-release"):
            copied = subprocess.run([runtime.cli, "cp", "%s:/%s" % (container, name), str(staging / name)],
                                    env=host.tool_env(), capture_output=True, text=True)
            if copied.returncode != 0:
                raise EmuError("could not copy %s out of %s: %s" % (name, tag, copied.stderr.strip()))
    finally:
        subprocess.run([runtime.cli, "rm", "-f", container], env=host.tool_env(), capture_output=True)

    manifest = _manifest("vm", arch, runtime, definition_hash)
    with open(staging / "image.json") as handle:
        manifest["image"] = json.load(handle)
    manifest["kernel_release"] = (staging / "kernel-release").read_text().strip()
    manifest["files"] = {name: {"sha256": _sha256_file(staging / name), "bytes": (staging / name).stat().st_size}
                         for name in VM_FILES}
    shutil.rmtree(directory, ignore_errors=True)
    staging.rename(directory)
    _write_manifest("vm", arch, manifest)
    return manifest


def ensure(kind, runtime_factory, arch, quiet=False, rebuild=False):
    """Return the manifest of an up-to-date image, building it when it is
    missing or was built from a different definition."""
    manifest = load_manifest(kind, arch)
    present = is_current(manifest)
    if present and kind == "vm":
        present = all((artifact_dir("vm", arch) / name).is_file() for name in VM_FILES)
    if present and kind == "container":
        present = runtime_factory().image_id(manifest["image_tag"]) == manifest.get("image_id")
    if present and not rebuild:
        return manifest
    check_definition()
    reason = "rebuilding" if manifest else "building"
    print("emu: %s the %s image for %s (the first build downloads packages and takes a while)" % (reason, kind, arch),
          flush=True)
    builder = build_vm if kind == "vm" else build_container
    return builder(runtime_factory(), arch, quiet=quiet)
