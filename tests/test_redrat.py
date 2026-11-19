import json
import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from emulator import cli, redrat, remote, window
from emulator.errors import EmuError
from emulator.run import RunOptions, launch


class Sender:
    def __init__(self):
        self.events = []

    def press(self, code):
        self.events.append(("press", code))

    def release(self, code):
        self.events.append(("release", code))


def profile(identifier="test-remote"):
    return {"version": 1, "id": identifier, "name": identifier,
            "buttons": {key: ["signal-" + key] for key in remote.CODES}}


class RedRatTests(unittest.TestCase):
    def setUp(self):
        self.sender = Sender()
        self.held = redrat.HeldKey(self.sender)

    def test_ir_is_ignored_without_focus_and_released_on_focus_loss(self):
        self.held.receive("ok", 1)
        self.assertEqual(self.sender.events, [])
        self.held.focus(True)
        self.held.receive("ok", 2)
        self.held.focus(False)
        self.held.receive("ok", 2.1)
        self.assertEqual(self.sender.events, [("press", 28), ("release", 28)])

    def test_frames_keep_one_key_held_until_quiet_timeout(self):
        self.held.focus(True)
        for now in (1, 1.1, 1.2):
            self.held.receive("up", now)
        self.held.expire(1.44)
        self.assertEqual(self.sender.events, [("press", 103)])
        self.held.expire(1.46)
        self.held.expire(2)
        self.assertEqual(self.sender.events, [("press", 103), ("release", 103)])

    def test_key_change_releases_previous_and_separate_presses_stay_separate(self):
        self.held.focus(True)
        self.held.receive("up", 1)
        self.held.receive("down", 1.1)
        self.held.receive("down", 2)
        self.assertEqual(self.sender.events, [("press", 103), ("release", 103), ("press", 108),
                                              ("release", 108), ("press", 108)])

    def test_every_mapped_key_uses_existing_target_codes(self):
        self.held.focus(True)
        for index, (key, _, code, _) in enumerate(remote.KEYS):
            self.held.receive(key, index)
            self.held.release()
            self.assertEqual(self.sender.events[-2:], [("press", code), ("release", code)])
        with self.assertRaises(EmuError):
            self.held.receive("not-a-key", 40)

    def test_profile_roundtrip_multiple_profiles_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)):
            redrat.save_profile(profile("first"))
            redrat.save_profile(profile("second"))
            self.assertEqual([item["id"] for item in redrat.profiles()], ["first", "second"])
            with self.assertRaises(EmuError):
                redrat.save_profile(profile("first"))
            self.assertEqual(redrat.load_profile("first"), profile("first"))
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), ["first.json", "second.json"])

    def test_profiles_allow_partial_and_empty_ir_mappings(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)):
            for identifier, buttons in (("partial", {"ok": ["signal-ok"]}), ("empty", {})):
                data = profile(identifier)
                data["buttons"] = buttons
                redrat.save_profile(data)
                self.assertEqual(redrat.load_profile(identifier), data)

    def test_profiles_reject_unknown_keys_invalid_ids_and_bad_signals(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)):
            for identifier in ("../escape", "", "/absolute", "Uppercase"):
                with self.assertRaises(EmuError):
                    redrat.load_profile(identifier)
            data = profile()
            data["buttons"]["unknown"] = ["signal-unknown"]
            with self.assertRaisesRegex(EmuError, "unknown"):
                redrat.save_profile(data)
            data = profile()
            data["buttons"]["ok"] = []
            with self.assertRaises(EmuError):
                redrat.save_profile(data)
            with self.assertRaises(EmuError):
                redrat.save_profile(profile("new"))
            Path(directory, "mismatch.json").write_text(json.dumps(profile("other")))
            with self.assertRaisesRegex(EmuError, "filename"):
                redrat.load_profile("mismatch")
            Path(directory, "broken.json").write_text("{")
            with self.assertRaises(EmuError):
                redrat.profiles()

    @patch.object(redrat, "command", return_value=["dotnet", "bridge", "list"])
    def test_probe_differentiates_absence_errors_and_malformed_output(self, command):
        for code, output, errors, expected in (
                (0, '{"devices":[]}', "", []),
                (1, "", "USB permission denied", EmuError),
                (0, "not json", "", EmuError),
                (0, '{"devices":[{}]}', "", EmuError)):
            with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], code, output, errors)):
                if expected is EmuError:
                    with self.assertRaises(EmuError):
                        redrat.devices()
                else:
                    self.assertEqual(redrat.devices(), expected)

    def test_receiver_selection_defaults_to_first_and_allows_explicit_override(self):
        devices = [{"id": "a", "name": "First"}, {"id": "b", "name": "Second"}]
        with patch.object(redrat, "devices", return_value=devices):
            self.assertEqual(redrat.select_device(), devices[0])
            self.assertEqual(redrat.select_device("b"), devices[1])
            with self.assertRaisesRegex(EmuError, "no RedRat"):
                redrat.select_device("missing")

    @patch.object(redrat, "command", return_value=["dotnet", "bridge", "validate-profile"])
    def test_sdk_validation_sends_candidate_without_opening_a_receiver(self, command):
        buttons = {"left": ["left"], "right": ["right"]}
        response = subprocess.CompletedProcess([], 0, '{"event":"profile-valid"}', "")
        with patch.object(redrat.subprocess, "run", return_value=response) as run:
            redrat.validate_signals(buttons)
        command.assert_called_once_with("validate-profile")
        self.assertEqual(json.loads(run.call_args.kwargs["input"])["buttons"], buttons)

    @patch.object(redrat, "command", return_value=["dotnet", "bridge", "validate-profile"])
    def test_sdk_validation_reports_conflicts_bad_responses_and_transport_failures(self, command):
        for result, message in (
                (subprocess.CompletedProcess([], 1, "", "Ambiguous profile: left and right"), "left and right"),
                (subprocess.CompletedProcess([], 0, "not json", ""), "invalid validation response"),
                (subprocess.CompletedProcess([], 0, '{"event":"ready"}', ""), "invalid validation response")):
            with self.subTest(message=message), patch.object(redrat.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(EmuError, message):
                    redrat.validate_signals({})
        for error in (OSError("cannot start"), subprocess.TimeoutExpired("bridge", 15)):
            with self.subTest(error=error), patch.object(redrat.subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(EmuError, "validation failed"):
                    redrat.validate_signals({})

    def test_ambiguous_profile_fails_before_building_or_starting_vm(self):
        with patch.object(redrat, "select_device", return_value={"id": "pico"}), \
                patch.object(redrat, "load_profile", return_value=profile()), \
                patch.object(redrat, "validate_signals", side_effect=EmuError("Ambiguous profile: left and right")), \
                patch("emulator.run.image.ensure") as build, patch("emulator.run.subprocess.Popen") as start:
            with self.assertRaisesRegex(EmuError, "left and right"):
                launch(RunOptions("vm", redrat_profile="test"))
            build.assert_not_called()
            start.assert_not_called()

    def test_source_stamp_changes_when_bridge_build_properties_change(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "SOURCE_DIR", Path(directory)):
            properties = Path(directory, "Directory.Build.props")
            properties.write_text("<Project />")
            before = redrat.source_digest()
            properties.write_text("<Project><PropertyGroup /></Project>")
            self.assertNotEqual(redrat.source_digest(), before)

    def test_redrat_device_requires_an_opted_in_profile(self):
        with self.assertRaisesRegex(EmuError, "requires --redrat-profile"):
            launch(RunOptions("container", redrat_device="a"))

    def test_redrat_profile_creation_is_a_config_command_not_a_run(self):
        output = io.StringIO()
        with patch.object(cli.window, "create_redrat_profile", return_value="living-room") as create, \
                patch.object(cli, "launch") as launch_run, contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["config", "redrat", "--device", "pico"]), 0)
        create.assert_called_once_with("pico")
        launch_run.assert_not_called()
        self.assertIn("saved RedRat profile living-room", output.getvalue())

    def test_profile_creation_starts_learning_ui_as_a_separate_task(self):
        response = subprocess.CompletedProcess(
            ["python", "-m", "emulator.gui.redrat"], 0, '{"profile":"living-room"}', "")
        with patch.object(redrat, "select_device", return_value={"id": "pico"}), \
                patch.object(window, "require_python", return_value="python"), \
                patch.object(window.subprocess, "run", return_value=response) as run:
            self.assertEqual(window.create_redrat_profile("pico"), "living-room")
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["python", "-m", "emulator.gui.redrat"])
        self.assertEqual(command[3:], ["--device", "pico"])

    def test_gui_probe_rejects_incompatible_qt_before_starting_a_window(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory, "PySide6")
            package.mkdir()
            (package / "QtWidgets.py").write_text("")
            with patch.dict(window.os.environ, {"PYTHONPATH": directory, "PYTHONDONTWRITEBYTECODE": "1"}):
                for version, accepted in (((6, 12, 0), False), ((6, 11, 3), True)):
                    (package / "__init__.py").write_text("__version_info__ = %r\n" % (version,))
                    with self.subTest(version=version):
                        self.assertEqual(window._has_qt(window.sys.executable), accepted)

    def test_profile_creation_reports_when_learning_ui_cannot_start(self):
        with patch.object(redrat, "select_device", return_value={"id": "pico"}), \
                patch.object(window, "require_python", return_value="python"), \
                patch.object(window.subprocess, "run", side_effect=OSError("not executable")):
            with self.assertRaisesRegex(EmuError, "profile creation could not start"):
                window.create_redrat_profile("pico")

    def test_remote_control_mode_option_is_removed(self):
        from emulator.cli import run_parser
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run_parser().parse_args(["--remote-control", "window"])

    def test_no_receiver_fails_before_building_or_starting_emulator(self):
        with patch.object(redrat, "devices", return_value=[]):
            with self.assertRaisesRegex(EmuError, "no RedRat"):
                launch(RunOptions("vm", redrat_profile="test"))


if __name__ == "__main__":
    unittest.main()
