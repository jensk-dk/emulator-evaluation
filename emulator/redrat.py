"""Host-side RedRat discovery, learned profiles, and held-key handling."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from . import host, remote
from .errors import EmuError
from .paths import BUILD_DIR, ROOT

PROFILE_DIR = ROOT / "remotes"
BRIDGE_DIR = BUILD_DIR / "host" / "redrat"
SDK_DIR = BUILD_DIR / "host" / "dotnet"
SOURCE_DIR = ROOT / "host" / "redrat"
RELEASE_SECONDS = 0.25
PROFILE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def dotnet():
    private = SDK_DIR / ("dotnet.exe" if os.name == "nt" else "dotnet")
    return str(private) if private.is_file() else host.find_tool("dotnet")


def environment():
    extra = {"DOTNET_NOLOGO": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1"}
    if (SDK_DIR / ("dotnet.exe" if os.name == "nt" else "dotnet")).is_file():
        extra["DOTNET_ROOT"] = str(SDK_DIR)
    if host.host_os() == "macos":
        paths = ["/opt/homebrew/lib", "/usr/local/lib", os.environ.get("DYLD_LIBRARY_PATH", "")]
        extra["DYLD_LIBRARY_PATH"] = os.pathsep.join(path for path in paths if path)
    return host.tool_env(extra)


def command(*arguments):
    executable = dotnet()
    bridge = BRIDGE_DIR / "RedRatBridge.dll"
    if not executable or not bridge.is_file():
        raise EmuError("RedRat support is not installed", hint=host.SETUP_HINT)
    return [executable, str(bridge)] + list(arguments)


def source_digest():
    digest = hashlib.sha256()
    for path in sorted(SOURCE_DIR.glob("*")):
        if path.suffix in (".cs", ".csproj", ".props"):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def installed():
    try:
        return (bool(dotnet()) and (BRIDGE_DIR / "RedRatBridge.dll").is_file()
                and (BRIDGE_DIR / "source.sha256").read_text().strip() == source_digest())
    except OSError:
        return False


def devices():
    """Enumerate through the SDK; no device is different from a failed probe."""
    try:
        done = subprocess.run(command("list"), capture_output=True, text=True, timeout=15, env=environment())
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EmuError("RedRat detection failed: %s" % error) from error
    if done.returncode:
        raise EmuError("RedRat detection failed: %s" % (done.stderr.strip() or "SDK exit %s" % done.returncode),
                       hint=host.SETUP_HINT)
    return decode_devices(done.stdout)


def decode_devices(text):
    try:
        found = json.loads(text)["devices"]
        if not isinstance(found, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
                or not isinstance(item.get("name"), str) for item in found):
            raise ValueError("invalid device list")
        return found
    except (ValueError, KeyError, TypeError) as error:
        raise EmuError("RedRat SDK returned an invalid device list: %s" % error) from error


def select_device(identifier=None):
    found = devices()
    if identifier:
        found = [item for item in found if item["id"] == identifier]
    if not found:
        raise EmuError("no RedRat device%s detected" % (" %r" % identifier if identifier else ""),
                       hint="connect the receiver and check USB permissions; " + host.SETUP_HINT)
    return found[0]


def validate_profile(data, identifier=None):
    if not isinstance(data, dict) or data.get("version") != 1:
        raise EmuError("a remote profile must have version 1")
    if not isinstance(data.get("id"), str) or not PROFILE_ID.fullmatch(data["id"]) or data["id"] == "new":
        raise EmuError("a remote profile id must contain lowercase letters, digits and single hyphens; 'new' is reserved")
    if identifier is not None and data["id"] != identifier:
        raise EmuError("remote profile id does not match its filename")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise EmuError("a remote profile must have a name")
    buttons = data.get("buttons")
    if not isinstance(buttons, dict):
        raise EmuError("a remote profile must have a buttons map")
    unknown = set(buttons) - set(remote.CODES)
    if unknown:
        raise EmuError("a remote profile contains unknown HbbTV keys: %s" % ", ".join(sorted(map(str, unknown))))
    for key, signals in buttons.items():
        if not isinstance(signals, list) or not signals or any(
                not isinstance(signal, (str, dict)) or not signal for signal in signals):
            raise EmuError("remote key %s needs one or more learned SDK signals" % key)
    return data


def validate_signals(buttons):
    """Use the playback decoder's timing and toggle rules without opening USB."""
    data = {"version": 1, "id": "learning", "name": "Learning", "buttons": buttons}
    try:
        done = subprocess.run(command("validate-profile"), input=json.dumps(data),
                              capture_output=True, text=True, timeout=15, env=environment())
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EmuError("RedRat profile validation failed: %s" % error) from error
    if done.returncode:
        raise EmuError("RedRat profile validation failed: %s" %
                       (done.stderr.strip() or "SDK exit %s" % done.returncode))
    try:
        if json.loads(done.stdout) != {"event": "profile-valid"}:
            raise ValueError("expected a profile-valid response")
    except ValueError as error:
        raise EmuError("RedRat SDK returned an invalid validation response: %s" % error) from error


def profile_path(identifier):
    if not isinstance(identifier, str) or not PROFILE_ID.fullmatch(identifier):
        raise EmuError("invalid remote profile id %r" % identifier)
    return PROFILE_DIR / (identifier + ".json")


def load_profile(identifier):
    path = profile_path(identifier)
    try:
        return validate_profile(json.loads(path.read_text(encoding="utf-8")), identifier)
    except (OSError, ValueError, EmuError) as error:
        raise EmuError("cannot read remote profile %s: %s" % (path, error)) from error


def profiles():
    return [load_profile(path.stem) for path in sorted(PROFILE_DIR.glob("*.json"))]


def save_profile(data):
    validate_profile(data)
    path = profile_path(data["id"])
    try:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        # A new profile never overwrites an already learned remote.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=PROFILE_DIR, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
        try:
            os.link(temporary, path)
        finally:
            temporary.unlink()
    except OSError as error:
        raise EmuError("cannot save remote profile %s: %s" % (path, error)) from error
    return path


class HeldKey:
    """IR frames keep a key down; the target compositor supplies repetition."""

    def __init__(self, sender):
        self.sender = sender
        self.code = None
        self.last = None
        self.focused = False

    def focus(self, focused):
        if not focused:
            self.release()
        self.focused = focused

    def receive(self, key, now):
        if not isinstance(key, str) or key not in remote.CODES:
            raise EmuError("RedRat SDK returned an unknown remote key %r" % key)
        if not self.focused:
            return
        self.expire(now)
        code = remote.CODES[key]
        if code != self.code:
            self.release()
            self.sender.press(code)
            self.code = code
        self.last = now

    def expire(self, now):
        if self.last is not None and now - self.last >= RELEASE_SECONDS:
            self.release()

    def release(self):
        if self.code is not None:
            self.sender.release(self.code)
        self.code = self.last = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "list", "stamp"))
    args = parser.parse_args(argv)
    try:
        if args.action == "check":
            if not installed():
                raise EmuError("RedRat SDK bridge is missing or out of date", hint=host.SETUP_HINT)
            # Enumeration also proves the runtime and native USB library load.
            devices()
        elif args.action == "stamp":
            (BRIDGE_DIR / "source.sha256").write_text(source_digest() + "\n")
        else:
            print(json.dumps({"devices": devices()}))
        return 0
    except EmuError as error:
        print("emu: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
