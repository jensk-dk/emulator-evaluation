import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtTest import QTest

from emulator import redrat, remote
from emulator.errors import EmuError
from emulator.gui import settings
from emulator.gui.redrat import LearningDialog, Receiver
from emulator.gui.viewer import Window


class Discovery(QObject):
    changed = Signal(list, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = Mock()

    def close(self):
        pass

    def refresh(self):
        pass


class RedRatGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        validator = patch.object(redrat, "validate_signals")
        self.validate_signals = validator.start()
        self.addCleanup(validator.stop)

    def test_repeated_framebuffer_signals_render_and_exit_cleanly(self):
        script = textwrap.dedent("""
            import threading
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            from emulator.gui.viewer import Display, Feed

            application = QApplication([])
            display = Display()
            display.on_size(1920, 1080)
            feed = Feed()
            feed.updated.connect(display.on_update)
            shown = threading.Event()
            finished = threading.Event()

            class Client:
                def shown(self):
                    shown.set()

            display.client = Client()

            def produce():
                for index in range(500):
                    shown.clear()
                    pixels = bytearray([index & 255, 25, 53, 0]) * (1280 * 720)
                    feed.updated.emit(0, 0, 1280, 720, pixels)
                    if not shown.wait(5):
                        return
                finished.set()

            thread = threading.Thread(target=produce, daemon=True)
            thread.start()
            timer = QTimer()
            timer.timeout.connect(lambda: application.quit()
                                  if finished.is_set() or not thread.is_alive() else None)
            timer.start(10)
            application.exec()
            thread.join(timeout=5)
            assert finished.is_set(), "frame updates stalled"
            color = display.image.pixelColor(0, 0)
            assert (color.red(), color.green(), color.blue()) == (53, 25, 499 & 255)
            assert display.image.pixelColor(1500, 900).red() == 0
        """)
        result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script],
                                capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_settings_join_keyboard_input_and_enable_redrat_by_profile(self):
        data = {"version": 1, "id": "first", "name": "First",
                "buttons": {key: ["signal-" + key] for key in remote.CODES}}
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)), \
                patch.object(settings, "Discovery", Discovery):
            redrat.save_profile(data)
            window = settings.SettingsWindow()
            self.assertNotIn("remote_control", window.fields)
            profile_field = window.fields["redrat_profile"]
            self.assertEqual(profile_field.create_button.text(), "Create new profile...")
            self.assertNotIn("new", [profile_field.combo.itemData(i) for i in range(profile_field.combo.count())])
            self.assertFalse(window.fields["redrat_profile"].widget.isEnabled())
            self.assertFalse(profile_field.create_button.isEnabled())
            window.receivers_changed([{"id": "pico", "name": "Pico"}], "")
            self.assertEqual(window.fields["redrat_device"].widget.text(), "")
            self.assertEqual(window.fields["redrat_device"].widget.placeholderText(), "Automatic: Pico (pico)")
            self.assertTrue(window.fields["redrat_profile"].widget.isEnabled())
            self.assertTrue(profile_field.create_button.isEnabled())
            self.assertFalse(window.fields["redrat_device"].widget.isEnabled())
            window.fields["redrat_profile"].set("first")
            window.fields["redrat_device"].set("pico")
            window.changed()
            self.assertTrue(window.fields["redrat_device"].widget.isEnabled())
            self.assertIn("--redrat-profile", window.arguments())
            self.assertIn("--redrat-device", window.arguments())
            window.receivers_changed([], "")
            self.assertFalse(window.fields["redrat_profile"].widget.isEnabled())
            window.fields["redrat_profile"].set(None)
            self.assertNotIn("--redrat-profile", window.arguments())
            self.assertNotIn("--redrat-device", window.arguments())
            window.reject()

    def test_create_profile_button_selects_profile_without_starting_emulator(self):
        profile = {"version": 1, "id": "second", "name": "Second",
                   "buttons": {key: ["signal-" + key] for key in remote.CODES}}
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)), \
                patch.object(settings, "Discovery", Discovery):
            window = settings.SettingsWindow()
            window.receivers_changed([{"id": "pico", "name": "Pico"},
                                      {"id": "pico-2", "name": "Pico 2"}], "")
            self.assertEqual(window.fields["redrat_device"].widget.placeholderText(), "Automatic: Pico (pico)")
            window.fields["redrat_device"].widget.setText("pico-2")
            window.show()
            def create_profile(device):
                redrat.save_profile(profile)
                return profile["id"]

            with patch.object(settings, "create_redrat_profile", side_effect=create_profile) as create:
                window.fields["redrat_profile"].create_button.click()
            create.assert_called_once_with("pico-2")
            self.assertEqual(window.fields["redrat_profile"].value(), "second")
            self.assertIn("--redrat-profile", window.arguments())
            self.assertTrue(window.isVisible())
            self.assertIsNone(window.chosen)
            window.reject()

    def test_profile_dropdown_refreshes_saved_profiles_without_restarting_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)), \
                patch.object(settings, "Discovery", Discovery):
            redrat.save_profile({"version": 1, "id": "first", "name": "First", "buttons": {}})
            window = settings.SettingsWindow()
            window.receivers_changed([{"id": "pico", "name": "Pico"}], "")
            profile_field = window.fields["redrat_profile"]
            profile_field.set("first")
            window.show()
            redrat.save_profile({"version": 1, "id": "new-remote", "name": "New remote", "buttons": {}})
            profile_field.combo.showPopup()
            try:
                self.assertGreaterEqual(profile_field.combo.findData("new-remote"), 0)
                self.assertEqual(profile_field.value(), "first")
                profile_field.set("new-remote")
                self.assertIn("new-remote", window.arguments())
            finally:
                profile_field.combo.hidePopup()
                window.reject()

    @patch.object(Receiver, "start")
    def test_learning_requires_two_distinct_presses_per_key_and_saves_all_keys(self, start):
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)):
            dialog = LearningDialog()
            dialog.name.setText("Test remote")
            dialog.identifier.setText("test")
            dialog.received({"event": "ready"})
            dialog.start_learning()
            with patch.object(dialog, "isActiveWindow", return_value=True):
                now = 1
                for key in remote.CODES:
                    for variant in (0, 1):
                        signal = {"event": "signal", "signal": "%s-%s" % (key, variant)}
                        with patch("emulator.gui.redrat.time.monotonic", return_value=now):
                            dialog.received(signal)
                        # Repeats of a held button must not fill the next slot/key.
                        with patch("emulator.gui.redrat.time.monotonic", return_value=now + 0.1):
                            dialog.received(signal)
                        now += 1
            self.assertEqual(dialog.index, 32)
            self.assertTrue(dialog.save.isEnabled())
            dialog.save_learned()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            saved = redrat.load_profile("test")
            self.assertEqual(set(saved["buttons"]), set(remote.CODES))
            self.assertTrue(all(len(values) == 2 for values in saved["buttons"].values()))

    @patch.object(Receiver, "start")
    def test_learning_rejects_sdk_conflict_before_advancing_and_allows_retry(self, start):
        dialog = LearningDialog()
        dialog.received({"event": "ready"})
        dialog.start_learning()
        index = next(i for i, entry in enumerate(remote.KEYS) if entry[0] == "right")
        dialog.index = index
        dialog.buttons = {"left": ["left-first", "left-second"]}
        dialog.show_prompt()
        self.validate_signals.side_effect = [
            EmuError("Ambiguous profile: buttons 'right' and 'left' match the same signal."), None, None]
        with patch.object(dialog, "isActiveWindow", return_value=True):
            with patch("emulator.gui.redrat.time.monotonic", return_value=1):
                dialog.received({"event": "signal", "signal": "different-json-but-same-sdk-signal"})
            self.assertEqual(dialog.index, index)
            self.assertNotIn("right", dialog.buttons)
            self.assertIn("'left'", dialog.prompt.text())
            self.assertIn("Capture rejected", dialog.prompt.text())
            self.assertTrue(dialog.capturing)
            self.assertFalse(dialog.save.isEnabled())
            for now, signal in ((2, "right-first"), (3, "right-second")):
                with patch("emulator.gui.redrat.time.monotonic", return_value=now):
                    dialog.received({"event": "signal", "signal": signal})
        self.assertEqual(dialog.index, index + 1)
        self.assertEqual(dialog.buttons["right"], ["right-first", "right-second"])
        self.assertEqual(self.validate_signals.call_args.args[0], dialog.buttons)
        dialog.reject()

    @patch.object(Receiver, "start")
    def test_save_revalidates_with_sdk_and_keeps_conflicting_profile_unsaved(self, start):
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)):
            dialog = LearningDialog()
            dialog.name.setText("Conflict")
            dialog.identifier.setText("conflict")
            dialog.buttons = {"left": ["first"], "right": ["second"]}
            dialog.index = len(remote.KEYS)
            dialog.show_prompt()
            self.validate_signals.side_effect = EmuError("Ambiguous profile: left and right")
            with patch("emulator.gui.redrat.QMessageBox.warning") as warning:
                dialog.save.click()
            self.assertIn("Ambiguous profile", warning.call_args.args[2])
            self.assertIsNone(dialog.profile)
            self.assertEqual(list(Path(directory).glob("*.json")), [])
            self.assertTrue(dialog.again.isEnabled())
            dialog.reject()

    @patch.object(Receiver, "start")
    def test_learning_skips_missing_keys_discards_partial_capture_and_allows_relearning(self, start):
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)):
            dialog = LearningDialog()
            dialog.name.setText("Partial remote")
            dialog.identifier.setText("partial")
            self.assertFalse(dialog.skip.isEnabled())
            dialog.received({"event": "ready"})
            self.assertFalse(dialog.skip.isEnabled())
            dialog.begin.click()
            first, second = [entry[0] for entry in remote.KEYS[:2]]
            with patch.object(dialog, "isActiveWindow", return_value=True):
                with patch("emulator.gui.redrat.time.monotonic", return_value=1):
                    dialog.received({"event": "signal", "signal": "partial-capture"})
                dialog.skip.click()
                self.assertNotIn(first, dialog.buttons)
                self.assertEqual(dialog.index, 1)
                self.assertFalse(dialog.save.isEnabled())
                dialog.again.click()
                self.assertEqual(dialog.index, 0)
                dialog.skip.click()
                for now in (2, 3):
                    with patch("emulator.gui.redrat.time.monotonic", return_value=now):
                        dialog.received({"event": "signal", "signal": "second-key"})
            while dialog.index < len(remote.KEYS):
                dialog.skip.click()
            self.assertFalse(dialog.skip.isEnabled())
            self.assertTrue(dialog.save.isEnabled())
            self.assertIn("31 skipped", dialog.prompt.text())
            dialog.again.click()
            self.assertTrue(dialog.skip.isEnabled())
            self.assertFalse(dialog.save.isEnabled())
            dialog.skip.click()
            dialog.save.click()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(redrat.load_profile("partial")["buttons"], {second: ["second-key", "second-key"]})

    @patch.object(Receiver, "start")
    def test_learning_can_skip_every_ir_key(self, start):
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)):
            dialog = LearningDialog()
            dialog.name.setText("Virtual only")
            dialog.identifier.setText("virtual-only")
            dialog.received({"event": "ready"})
            dialog.begin.click()
            for _ in remote.KEYS:
                dialog.skip.click()
            dialog.save.click()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(redrat.load_profile("virtual-only")["buttons"], {})

    @patch.object(Receiver, "start")
    def test_cancel_does_not_save_profile_and_receiver_failure_disables_save(self, start):
        with tempfile.TemporaryDirectory() as directory, patch.object(redrat, "PROFILE_DIR", Path(directory)):
            dialog = LearningDialog()
            dialog.received({"event": "ready"})
            dialog.start_learning()
            dialog.failed("device unplugged")
            self.assertFalse(dialog.skip.isEnabled())
            self.assertFalse(dialog.save.isEnabled())
            self.assertIn("device unplugged", dialog.prompt.text())
            dialog.reject()
            self.assertEqual(list(Path(directory).glob("*.json")), [])

    @patch.object(Receiver, "start")
    @patch("emulator.gui.viewer.rfb.Client.start")
    def test_viewer_routes_ir_only_when_display_focused_and_releases_on_deactivation(self, client_start, receiver_start):
        args = SimpleNamespace(audio_control=None, title="IR test", display=("localhost", 1),
                               fullscreen=False, redrat_profile="test", redrat_device="pico")
        sender = Mock()
        window = Window(args, sender)
        with patch.object(window, "isActiveWindow", return_value=False):
            window.ir_event({"event": "key", "key": "ok"})
            sender.press.assert_not_called()
        with patch.object(window, "isActiveWindow", return_value=True):
            window.ir_event({"event": "key", "key": "ok"})
            sender.press.assert_called_once_with(remote.CODES["ok"])
        with patch.object(window, "isActiveWindow", return_value=False):
            window.changeEvent(QEvent(QEvent.Type.ActivationChange))
            sender.release.assert_called_once_with(remote.CODES["ok"])
        window.close()

    @patch("emulator.gui.viewer.rfb.Client.start")
    def test_remote_window_starts_hidden_and_toolbar_and_hotkey_toggle_it(self, client_start):
        window = Window(SimpleNamespace(audio_control=None, title="Input test", display=("localhost", 1),
                                        fullscreen=False, redrat_profile=None, redrat_device=None), Mock())
        window.show()
        QTest.qWait(20)
        self.assertFalse(window.remote_window.isVisible())
        window.remote_action.trigger()
        self.assertTrue(window.remote_window.isVisible())
        window.remote_action.trigger()
        self.assertFalse(window.remote_window.isVisible())
        hotkey = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R,
                           Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        window.key_event(hotkey, True)
        self.assertTrue(window.remote_window.isVisible())
        window.key_event(hotkey, True)
        self.assertFalse(window.remote_window.isVisible())
        window.close()

    def test_receiver_handles_json_lines_and_closes_its_helper(self):
        helper = (
            "import json,sys\n"
            "print(json.dumps({'event':'ready','device':{'name':'fake'}}), flush=True)\n"
            "print(json.dumps({'event':'key','key':'up'}), flush=True)\n"
            "for line in sys.stdin:\n"
            " if json.loads(line).get('do') == 'quit': break\n")
        receiver = Receiver()
        events, failures = [], []
        receiver.received.connect(events.append)
        receiver.failed.connect(failures.append)
        with patch.object(redrat, "command", return_value=[sys.executable, "-u", "-c", helper]):
            receiver.start()
            for _ in range(100):
                if len(events) == 2 or failures:
                    break
                QTest.qWait(20)
            receiver.close()
        self.assertEqual([event["event"] for event in events], ["ready", "key"])
        self.assertEqual(failures, [])
        self.assertEqual(receiver.process.exitCode(), 0)

    def test_receiver_reports_malformed_sdk_output_instead_of_ignoring_it(self):
        receiver = Receiver()
        failures = []
        receiver.failed.connect(failures.append)
        with patch.object(redrat, "command", return_value=[sys.executable, "-u", "-c", "print('not JSON',flush=True)"]):
            receiver.start()
            for _ in range(100):
                if failures:
                    break
                QTest.qWait(20)
            receiver.close()
        self.assertEqual(len(failures), 1)
        self.assertIn("invalid RedRat SDK response", failures[0])


if __name__ == "__main__":
    unittest.main()
