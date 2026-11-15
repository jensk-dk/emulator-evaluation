"""The settings window: what the launcher shows when it is started without
arguments.

    python -m emulator.gui.settings [--script JSON]

It offers every setting that "emu run" takes as an argument: the form is made
from the launcher's own argument parser (emulator/cli.py), so a new argument
has a field here without a change to this file. Start prints the arguments
the user chose, as one line of JSON on standard output, and ends; the launcher
then runs with them. Closing the window prints that nothing was chosen.

    {"arguments": ["run", "--mode", "vm", "--arch", "arm64"]}
    {"arguments": null}

--script is for the launcher's checks: {"set": {FIELD: VALUE, ...}, "press":
"start" | "close", "save": PATH}. The fields are set and the button is clicked
as a person would, and the answer also lists the window's fields.
"""
import argparse
import contextlib
import io
import json
import shlex
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from .. import catalog, drivers, remote
from ..cli import run_parser
from ..run import KNOWN_OPTIONS

DEFAULT = "(default)"
# Where a field is shown, and what it is called. An argument that is not
# named here gets a field under "Other", named after the argument.
GROUPS = (
    ("Target", (("mode", "Mode"), ("arch", "VM guest CPU"), ("workload", "Workload"),
                ("workload_args", "Workload arguments"), ("cpus", "CPUs"), ("memory", "Memory (MiB)"))),
    ("Display", (("window_mode", "Window mode"), ("remote_control", "Remote control"),
                 ("resolution", "Resolution"), ("graphics", "Graphics"), ("screenshot", "Save captures to"))),
    ("Sound", (("mute", "Start muted"),)),
    ("Options", (("option", "Emulator options"), ("driver", "Driver features"),
                 ("emulator_arg", "Emulator arguments"))),
    ("Run", (("record", "Record the results"), ("repeat", "Repeat"), ("timeout", "Timeout (seconds)"),
             ("rebuild", "Rebuild the target image first"))),
)
# Two arguments, one field: the display's window mode.
WINDOW_MODES = (("none", []), ("window", ["--window"]), ("full screen", ["--fullscreen"]))
RANGES = {"cpus": (1, 256, 1), "memory": (128, 1048576, 256), "repeat": (1, 1000, 1)}
LABELS = {"container": "container", "vm": "VM", "native": "native (the host's own)", "arm32": "ARM32", "arm64": "ARM64",
          "x86_64": "x86-64"}


class Field:
    """One setting: its widget, and the launcher arguments it stands for."""

    def __init__(self, name, action=None):
        self.name = name
        self.action = action
        self.widget = None

    def arguments(self):
        raise NotImplementedError

    def set(self, value):
        raise NotImplementedError


class ChoiceField(Field):
    def __init__(self, name, action, choices, default):
        super().__init__(name, action)
        self.default = default
        self.widget = QComboBox()
        if default is None:
            self.widget.addItem(DEFAULT, None)
        for choice in choices:
            self.widget.addItem(LABELS.get(choice, str(choice)), choice)
        if default is not None:
            self.widget.setCurrentIndex(self.widget.findData(default))

    def value(self):
        return self.widget.currentData()

    def arguments(self):
        value = self.value()
        return [] if value in (None, self.default) else [self.action.option_strings[0], str(value)]

    def set(self, value):
        index = self.widget.findData(value)
        if index < 0:
            raise ValueError("%s has no choice %r" % (self.name, value))
        self.widget.setCurrentIndex(index)


class WindowModeField(Field):
    def __init__(self):
        super().__init__("window_mode")
        self.widget = QComboBox()
        for label, arguments in WINDOW_MODES:
            self.widget.addItem(label, arguments)
        self.widget.setToolTip("Whether the emulator's display is shown: not at all, in a window with a toolbar, or "
                               "full screen. Ctrl+Alt+F or F11 switches between the two while it runs.")

    def arguments(self):
        return list(self.widget.currentData())

    def set(self, value):
        index = self.widget.findText(value)
        if index < 0:
            raise ValueError("no window mode %r" % value)
        self.widget.setCurrentIndex(index)


class FlagField(Field):
    def __init__(self, name, action):
        super().__init__(name, action)
        self.widget = QCheckBox()

    def arguments(self):
        return [self.action.option_strings[0]] if self.widget.isChecked() else []

    def set(self, value):
        self.widget.setChecked(bool(value))


class NumberField(Field):
    def __init__(self, name, action):
        super().__init__(name, action)
        low, high, step = RANGES.get(name, (0, 1000000, 1))
        self.widget = QSpinBox()
        self.widget.setRange(low, high)
        self.widget.setSingleStep(step)
        self.widget.setValue(action.default if action.default is not None else low)

    def arguments(self):
        value = self.widget.value()
        return [] if value == self.action.default else [self.action.option_strings[0], str(value)]

    def set(self, value):
        self.widget.setValue(int(value))


class TextField(Field):
    """One value, several (an argument that may be given more than once), or
    the workload's own arguments."""

    def __init__(self, name, action, placeholder=""):
        super().__init__(name, action)
        self.widget = QLineEdit()
        self.widget.setPlaceholderText(placeholder)
        self.widget.setMinimumWidth(300)

    def arguments(self):
        text = self.widget.text().strip()
        if not text:
            return []
        if self.action.nargs == argparse.REMAINDER:
            return ["--"] + shlex.split(text)
        if isinstance(self.action, argparse._AppendAction):
            found = []
            for item in shlex.split(text):
                found += [self.action.option_strings[0], item]
            return found
        return [self.action.option_strings[0], text]

    def set(self, value):
        self.widget.setText(str(value))


class FolderField(TextField):
    def __init__(self, name, action):
        super().__init__(name, action, "a folder")
        self.edit = self.widget
        self.widget = QWidget()
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.edit)
        browse = QPushButton("Choose...")
        browse.clicked.connect(self.choose)
        row.addWidget(browse)

    def choose(self):
        chosen = QFileDialog.getExistingDirectory(self.widget, "Folder for the captures")
        if chosen:
            self.edit.setText(chosen)

    def arguments(self):
        text = self.edit.text().strip()
        return [self.action.option_strings[0], text] if text else []

    def set(self, value):
        self.edit.setText(str(value))


def make_fields(parser):
    """A field for every argument of the parser; the window mode's two
    arguments share one."""
    fields = {}
    merged = {argument for _, arguments in WINDOW_MODES for argument in arguments}
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if action.option_strings and action.option_strings[0] in merged:
            fields.setdefault("window_mode", WindowModeField())
            continue
        name = action.dest
        if name == "workload":
            choices = [item["id"] for item in catalog.workloads()["workloads"] if item["status"] == "implemented"]
            field = ChoiceField(name, action, choices, action.default)
        elif action.choices:
            field = ChoiceField(name, action, list(action.choices), action.default)
        elif isinstance(action, argparse._StoreTrueAction):
            field = FlagField(name, action)
        elif action.type is int:
            field = NumberField(name, action)
        elif name == "screenshot":
            field = FolderField(name, action)
        else:
            placeholder = action.metavar if isinstance(action.metavar, str) else ""
            if isinstance(action, argparse._AppendAction):
                placeholder += " ..."
            elif action.nargs == argparse.REMAINDER:
                placeholder = "passed to the workload"
            field = TextField(name, action, placeholder)
        if action.help and not field.widget.toolTip():
            field.widget.setToolTip(action.help % {"default": action.default})
        fields[name] = field
    fields["option"].widget.setToolTip(
        "Emulator options, KEY=VALUE, separated by spaces:\n" +
        "\n".join("  %s: %s" % item for item in sorted(KNOWN_OPTIONS.items())))
    fields["driver"].widget.setToolTip(
        "How a target driver feature is provided, FEATURE=STRATEGY (emulated, mocked, host or none), separated by "
        "spaces:\n" + "\n".join("  %s: %s" % item for item in sorted(drivers.FEATURES.items())))
    return fields


class SettingsWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Emulator")
        self.parser = run_parser()
        self.fields = make_fields(self.parser)
        self.chosen = None
        layout = QVBoxLayout(self)
        placed = set()
        columns = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        columns.addLayout(left)
        columns.addLayout(right)
        layout.addLayout(columns)
        groups = list(GROUPS)
        other = tuple((name, name.replace("_", " ").capitalize()) for name in self.fields
                      if name not in {field for _, items in GROUPS for field, _ in items})
        if other:
            groups.append(("Other", other))
        for index, (title, items) in enumerate(groups):
            box = QGroupBox(title)
            form = QFormLayout(box)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            for name, label in items:
                if name in self.fields:
                    form.addRow(label, self.fields[name].widget)
                    placed.add(name)
            (left if index < 2 else right).addWidget(box)
        left.addStretch(1)
        right.addStretch(1)

        # The same run as a command line, to copy or to learn from.
        self.command = QPlainTextEdit()
        self.command.setReadOnly(True)
        self.command.setFixedHeight(58)
        self.command.setToolTip("The command line that starts the emulator with these settings")
        font = QFont(self.command.font())
        font.setFamilies(["Menlo", "Consolas", "DejaVu Sans Mono", "monospace"])
        self.command.setFont(font)
        layout.addWidget(self.command)
        self.problem = QLabel()
        self.problem.setStyleSheet("color: #c0392b;")
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        self.start_button = QPushButton("Start")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.start)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)

        for field in self.fields.values():
            for widget in [field.widget] + field.widget.findChildren(QWidget):
                for signal in ("currentIndexChanged", "toggled", "valueChanged", "textChanged"):
                    if hasattr(widget, signal):
                        getattr(widget, signal).connect(self.changed)
        self.changed()

    def arguments(self):
        found = ["run"]
        tail = []
        for name, field in self.fields.items():
            if name == "arch" and self.fields["mode"].value() != "vm":
                continue                    # the guest CPU is a VM's
            given = field.arguments()
            if given[:1] == ["--"]:
                tail = given                # the workload's own arguments come last
            else:
                found += given
        return found + tail

    def changed(self, *ignored):
        self.fields["arch"].widget.setEnabled(self.fields["mode"].value() == "vm")
        window = bool(self.fields["window_mode"].arguments())
        remote_field = self.fields.get("remote_control")
        if remote_field is not None:
            remote_field.widget.setToolTip(
                "Remote control input. With a window the host keyboard is the remote control (the arrow keys, Enter "
                "and a key for every other one); \"window\" adds an on-screen remote control. Choosing a mode here "
                "shows the display in a window." if not window else
                "Remote control input: keys, the host keyboard while the emulator's window has the focus; window, "
                "an on-screen remote control as well; redrat, a RedRat infrared receiver (not implemented).")
        self.command.setPlainText("emu " + " ".join(shlex.quote(part) for part in self.arguments()))
        self.problem.setText("")

    def start(self):
        arguments = self.arguments()
        # The launcher's own parser has the last word on what is valid; it
        # says what is wrong on its error stream and ends.
        said = io.StringIO()
        try:
            with contextlib.redirect_stderr(said):
                self.parser.parse_args(arguments[1:])
        except SystemExit:
            lines = [line for line in said.getvalue().splitlines() if "error:" in line]
            self.problem.setText(lines[-1].split("error:", 1)[1].strip().capitalize() if lines
                                 else "The launcher does not accept these settings.")
            return
        self.chosen = arguments
        self.accept()


def run_script(window, script, answer):
    """Set fields and press a button as a person would, for a check."""
    from PySide6.QtTest import QTest
    for name, value in (script.get("set") or {}).items():
        window.fields[name].set(value)
    answer["fields"] = sorted(window.fields)
    answer["enabled"] = {name: field.widget.isEnabled() for name, field in window.fields.items()}
    answer["command"] = window.command.toPlainText()
    answer["visible"] = window.isVisible()
    if script.get("save"):
        answer["saved"] = bool(window.grab().save(script["save"]))
    button = window.close_button if script.get("press") == "close" else window.start_button
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    answer["problem"] = window.problem.text()
    if window.isVisible():      # the settings were refused: nothing to wait for
        window.reject()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="emulator.gui.settings", description=__doc__.splitlines()[0])
    parser.add_argument("--script", type=json.loads, metavar="JSON")
    args = parser.parse_args(argv)
    application = QApplication(sys.argv[:1])
    application.setApplicationName("Emulator")
    window = SettingsWindow()
    answer = {}
    window.show()
    window.raise_()
    window.activateWindow()
    if args.script is not None:
        QTimer.singleShot(300, lambda: run_script(window, args.script, answer))
    window.exec()
    answer["arguments"] = window.chosen
    print(json.dumps(answer), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
