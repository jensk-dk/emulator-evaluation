"""Qt integration for the RedRat SDK helper and guided remote learning."""
import argparse
import json
import sys
import time

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QVBoxLayout)

from .. import redrat, remote
from ..errors import EmuError


class Discovery(QObject):
    changed = Signal(list, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.closing = False
        self.process = QProcess(self)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.timed_out)
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self.closing = False
        try:
            command = redrat.command("list")
        except EmuError as error:
            self.changed.emit([], str(error))
            return
        environment = QProcessEnvironment()
        for key, value in redrat.environment().items():
            environment.insert(key, value)
        self.process.setProcessEnvironment(environment)
        self.process.start(command[0], command[1:])
        self.deadline.start(15000)

    def finished(self, code, status):
        self.deadline.stop()
        output = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        errors = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if self.closing:
            return
        try:
            if code:
                raise EmuError(errors or "RedRat detection exited with code %s" % code)
            self.changed.emit(redrat.decode_devices(output), "")
        except EmuError as error:
            self.changed.emit([], str(error))

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and not self.closing:
            self.deadline.stop()
            self.changed.emit([], "Cannot start RedRat detection: " + self.process.errorString())

    def timed_out(self):
        self.closing = True
        self.process.kill()
        self.changed.emit([], "RedRat detection timed out after 15 seconds")

    def close(self):
        self.closing = True
        self.timer.stop()
        self.deadline.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1500)


class Receiver(QObject):
    received = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.buffer = b""
        self.errors = ""
        self.closing = False
        self.ready = False
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.readyReadStandardError.connect(self.read_errors)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(lambda: self.fail("the RedRat receiver did not become ready within 15 seconds"))

    def start(self, device=None, profile=None):
        arguments = ["listen"]
        if device:
            arguments += ["--device", device]
        if profile:
            arguments += ["--profile", str(redrat.profile_path(profile))]
        command = redrat.command(*arguments)
        environment = QProcessEnvironment()
        for key, value in redrat.environment().items():
            environment.insert(key, value)
        self.process.setProcessEnvironment(environment)
        self.process.start(command[0], command[1:])
        self.deadline.start(15000)

    def read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        if len(self.buffer) > 1024 * 1024:
            self.fail("RedRat SDK output exceeded one megabyte without being consumed")
            return
        while b"\n" in self.buffer and not self.closing:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or event.get("event") not in ("ready", "signal", "key", "unmapped"):
                    raise ValueError("invalid event")
                if event["event"] == "ready":
                    self.ready = True
                    self.deadline.stop()
                self.received.emit(event)
            except (ValueError, UnicodeError) as error:
                self.fail("invalid RedRat SDK response: %s" % error)

    def read_errors(self):
        text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        self.errors = (self.errors + text)[-4000:]
        if text.strip():
            print("emu: RedRat: " + text.strip(), file=sys.stderr, flush=True)

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.fail("cannot start RedRat SDK helper: " + self.process.errorString())

    def finished(self, code, status):
        self.read_errors()
        if not self.closing:
            self.fail("RedRat receiver stopped (exit %s): %s" % (code, self.errors.strip() or "device connection lost"))

    def fail(self, text):
        if not self.closing:
            self.close()
            self.failed.emit(text)

    def close(self):
        self.closing = True
        self.deadline.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.write(b'{"do":"quit"}\n')
            self.process.closeWriteChannel()
            if not self.process.waitForFinished(1500):
                self.process.terminate()
                if not self.process.waitForFinished(1500):
                    self.process.kill()
                    self.process.waitForFinished(1500)


class LearningDialog(QDialog):
    def __init__(self, device=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Learn a remote control")
        self.profile = None
        self.buttons = {}
        self.index = 0
        self.last_frame = None
        self.capturing = False
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Give the remote a name, then press each requested button twice, releasing it between presses.\n"
            "The two captures allow for remotes with alternating (toggle) signals.\n"
            "Use Skip key for buttons your remote lacks; they remain available on the virtual remote.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Living room remote")
        self.identifier = QLineEdit()
        self.identifier.setPlaceholderText("living-room")
        form.addRow("Name", self.name)
        form.addRow("Profile id", self.identifier)
        layout.addLayout(form)
        self.prompt = QLabel("Opening the RedRat receiver...")
        layout.addWidget(self.prompt)
        self.begin = QPushButton("Start learning")
        self.begin.setEnabled(False)
        self.begin.clicked.connect(self.start_learning)
        layout.addWidget(self.begin)
        self.skip = QPushButton("Skip key")
        self.skip.setEnabled(False)
        self.skip.clicked.connect(self.skip_key)
        layout.addWidget(self.skip)
        self.again = QPushButton("Relearn previous key")
        self.again.setEnabled(False)
        self.again.clicked.connect(self.previous)
        layout.addWidget(self.again)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save.setEnabled(False)
        buttons.accepted.connect(self.save_learned)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.receiver = Receiver(self)
        self.receiver.received.connect(self.received)
        self.receiver.failed.connect(self.failed)
        self.finished.connect(lambda _: self.receiver.close())
        try:
            self.receiver.start(device)
        except EmuError as error:
            self.failed(str(error))

    def start_learning(self):
        self.capturing = True
        self.begin.setEnabled(False)
        self.begin.setText("Learning...")
        self.show_prompt()

    def show_prompt(self):
        self.again.setEnabled(self.index > 0)
        self.skip.setEnabled(self.index < len(remote.KEYS))
        if self.index == len(remote.KEYS):
            self.capturing = False
            self.prompt.setText("Learning complete: %d learned, %d skipped. Save to add this remote to the repository." %
                                (len(self.buttons), len(remote.KEYS) - len(self.buttons)))
            self.save.setEnabled(True)
            return
        key, label, _, _ = remote.KEYS[self.index]
        self.prompt.setText("%d / 32: press %s (%d / 2 captured)" %
                            (self.index + 1, label, len(self.buttons.get(key, []))))

    def received(self, event):
        if event["event"] == "ready":
            self.begin.setEnabled(True)
            self.prompt.setText("Receiver ready. Click Start learning.")
        elif event["event"] == "signal" and self.capturing and self.isActiveWindow():
            now = time.monotonic()
            previous, self.last_frame = self.last_frame, now
            # Repeated IR frames from one held press are not separate captures.
            if previous is not None and now - previous < 0.5:
                return
            signal = event.get("signal")
            if not isinstance(signal, (str, dict)) or not signal:
                self.failed("The SDK returned no learnable signal.")
                return
            key = remote.KEYS[self.index][0]
            candidate = dict(self.buttons)
            candidate[key] = candidate.get(key, []) + [signal]
            try:
                redrat.validate_signals(candidate)
            except EmuError as error:
                self.prompt.setText("%s\nCapture rejected for %s. Release the buttons and retry, "
                                    "relearn the previous key, or skip this key." % (error, remote.LABELS[key]))
                return
            self.buttons = candidate
            if len(self.buttons[key]) == 2:
                self.index += 1
            self.show_prompt()

    def skip_key(self):
        self.buttons.pop(remote.KEYS[self.index][0], None)
        self.index += 1
        self.show_prompt()

    def previous(self):
        self.index = max(0, self.index - 1)
        for key, _, _, _ in remote.KEYS[self.index:]:
            self.buttons.pop(key, None)
        self.capturing = True
        self.save.setEnabled(False)
        self.show_prompt()

    def failed(self, text):
        self.capturing = False
        self.begin.setEnabled(False)
        self.skip.setEnabled(False)
        self.again.setEnabled(False)
        self.save.setEnabled(False)
        self.prompt.setText("RedRat error: " + text)

    def save_learned(self):
        data = {"version": 1, "id": self.identifier.text().strip(), "name": self.name.text().strip(),
                "buttons": self.buttons}
        try:
            redrat.validate_signals(self.buttons)
            redrat.save_profile(data)
        except EmuError as error:
            QMessageBox.warning(self, "Cannot save remote", str(error))
            return
        self.profile = data["id"]
        self.accept()


def learn_profile(device=None, parent=None):
    dialog = LearningDialog(device, parent)
    return dialog.profile if dialog.exec() == QDialog.DialogCode.Accepted else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device")
    args = parser.parse_args(argv)
    application = QApplication(sys.argv[:1])
    application.setApplicationName("Emulator")
    try:
        profile = learn_profile(args.device)
        print(json.dumps({"profile": profile}), flush=True)
        return 0
    except EmuError as error:
        print("emu: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
