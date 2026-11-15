"""The emulator's display window.

    python -m emulator.gui.viewer --display ADDRESS [--title TEXT] [--fullscreen]
        [--remote-control keys|window] [--keys-exec JSON | --keys-listen PORT]
        [--audio-control PORT] [--control]

It shows the target's display, which it follows with the remote framebuffer
protocol (emulator/rfb.py): ADDRESS is a socket path or HOST:PORT. The display
is scaled to the window, keeping its shape.

Windowed, it has a small toolbar: mute, 1:1 (one pixel of the display on one
pixel of the screen), full screen, and the on-screen remote control. Full
screen has no toolbar; Ctrl+Alt+F switches between the two (on a Mac the
Control or the Command key with Option), and so does F11.

While the window has the input focus, host keys are remote control keys
(emulator/remote.py): the arrow keys, Enter, and a key for every other one.

Closing the window ends the program; the launcher then ends the emulator.

--control is for the launcher's checks and for scripts: commands as JSON
lines on standard input, one answer line each on standard output.
"""
import argparse
import json
import sys
import threading

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QMainWindow, QToolBar, QWidget

from .. import hostaudio, remote, rfb
from .remote_window import RemoteControlWindow

QT_KEY_NAMES = {
    Qt.Key.Key_Up.value: "Up", Qt.Key.Key_Down.value: "Down", Qt.Key.Key_Left.value: "Left",
    Qt.Key.Key_Right.value: "Right", Qt.Key.Key_Return.value: "Return", Qt.Key.Key_Enter.value: "Enter",
    Qt.Key.Key_Backspace.value: "Backspace", Qt.Key.Key_Escape.value: "Escape", Qt.Key.Key_Space.value: "Space",
    Qt.Key.Key_PageUp.value: "PageUp", Qt.Key.Key_PageDown.value: "PageDown",
}
QT_KEYS_BY_NAME = {name: key for key, name in QT_KEY_NAMES.items()}
# The largest display QEMU 8.2's display server serves.
VNC_LIMIT = (2560, 2048)
COMMAND_KEYS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier


def host_key_name(key):
    """The name emulator/remote.py has for a key of the host keyboard."""
    if key in QT_KEY_NAMES:
        return QT_KEY_NAMES[key]
    if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value or Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
        return chr(key)
    return None


def qt_key(name):
    """The Qt key for a host key's name: one of the names above, a letter or
    a digit, or any other key by Qt's own name for it (F11)."""
    if name in QT_KEYS_BY_NAME:
        return QT_KEYS_BY_NAME[name]
    if len(name) == 1:
        return ord(name)
    return getattr(Qt.Key, "Key_" + name).value


class Feed(QObject):
    """Takes what the display's client hears on its thread to the window's."""
    sized = Signal(int, int)
    updated = Signal(int, int, int, int, object)
    state = Signal(str)


class Display(QWidget):
    """The target's display, scaled to the widget and centred in it."""

    def __init__(self):
        super().__init__()
        self.image = None
        self.message = "waiting for the target's display"
        self.client = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(160, 90)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def display_size(self):
        return (self.image.width(), self.image.height()) if self.image is not None else (1920, 1080)

    def natural_size(self):
        """The widget size at which one pixel of the display is one pixel of
        the screen."""
        ratio = self.devicePixelRatioF()
        width, height = self.display_size()
        return QSize(round(width / ratio), round(height / ratio))

    def sizeHint(self):
        return self.natural_size()

    def on_size(self, width, height):
        self.image = QImage(width, height, QImage.Format.Format_RGB32)
        self.image.fill(QColor(0, 0, 0))
        self.update()

    def on_update(self, x, y, width, height, pixels):
        if self.image is not None:
            part = QImage(pixels, width, height, width * 4, QImage.Format.Format_RGB32)
            painter = QPainter(self.image)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawImage(x, y, part)
            painter.end()
            self.update()
        if self.client is not None:
            self.client.shown()

    def on_state(self, text):
        self.message = text
        self.update()

    def shown_rect(self):
        """Where in the widget the display is drawn."""
        width, height = self.display_size()
        scale = min(self.width() / width, self.height() / height)
        shown = QSize(max(1, round(width * scale)), max(1, round(height * scale)))
        return QRect(QPoint((self.width() - shown.width()) // 2, (self.height() - shown.height()) // 2), shown)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        if self.image is not None:
            target = self.shown_rect()
            exact = target.size() == self.natural_size()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not exact)
            painter.drawImage(target, self.image)
        if self.message:
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
        painter.end()


def _icon(draw, palette):
    """A toolbar icon drawn in the window's text colour, so that it reads on
    a light and on a dark toolbar."""
    icon = QIcon()
    for size in (20, 40):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 20, size / 20)
        colour = palette.color(QPalette.ColorRole.WindowText)
        painter.setPen(QPen(colour, 1.6))
        painter.setBrush(colour)
        draw(painter, colour)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def _draw_speaker(painter, colour, muted):
    painter.drawPolygon(QPolygonF([QPointF(3, 8), QPointF(6, 8), QPointF(10, 4), QPointF(10, 16), QPointF(6, 12),
                                   QPointF(3, 12)]))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if muted:
        painter.drawLine(QPointF(13, 7), QPointF(18, 13))
        painter.drawLine(QPointF(18, 7), QPointF(13, 13))
    else:
        painter.drawArc(QRectF(8, 6, 6, 8), -60 * 16, 120 * 16)
        painter.drawArc(QRectF(7, 3, 10, 14), -60 * 16, 120 * 16)


def _draw_one_to_one(painter, colour):
    font = painter.font()
    font.setPixelSize(10)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, 20, 20), Qt.AlignmentFlag.AlignCenter, "1:1")


def _draw_full_screen(painter, colour):
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for x, y, dx, dy in ((3, 3, 1, 1), (17, 3, -1, 1), (3, 17, 1, -1), (17, 17, -1, -1)):
        painter.drawLine(QPointF(x, y), QPointF(x + 5 * dx, y))
        painter.drawLine(QPointF(x, y), QPointF(x, y + 5 * dy))


def _draw_remote(painter, colour):
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(6, 2, 8, 16), 2, 2)
    painter.setBrush(colour)
    painter.drawEllipse(QPointF(10, 6), 1.2, 1.2)
    for y in (10, 13):
        for x in (8.5, 11.5):
            painter.drawEllipse(QPointF(x, y), 0.6, 0.6)


class Window(QMainWindow):
    def __init__(self, args, sender):
        super().__init__()
        self.sender = sender
        self.args = args
        self.cut_noted = False
        self.audio_port = args.audio_control
        self.keys_on = args.remote_control in ("keys", "window")
        self.muted = None
        self.pressed = {}               # host key -> remote control key code, while it is down
        self.setWindowTitle(args.title)

        self.display = Display()
        self.setCentralWidget(self.display)
        self.feed = Feed()
        self.feed.sized.connect(self.on_size)
        self.feed.updated.connect(self.display.on_update)
        self.feed.state.connect(self.display.on_state)
        self.client = rfb.Client(args.display, self.feed.sized.emit, self.feed.updated.emit, self.feed.state.emit)
        self.display.client = self.client
        self.fitted = None              # the window size this program last chose, if it still has it

        palette = self.palette()
        self.toolbar = QToolBar("Display")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(20, 20))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(self.toolbar)
        self.sound_icons = {False: _icon(lambda p, c: _draw_speaker(p, c, False), palette),
                            True: _icon(lambda p, c: _draw_speaker(p, c, True), palette)}
        self.mute_action = QAction(self.sound_icons[False], "Mute", self)
        self.mute_action.setCheckable(True)
        self.mute_action.triggered.connect(self.set_muted)
        self.toolbar.addAction(self.mute_action)
        self.one_action = QAction(_icon(_draw_one_to_one, palette), "1:1", self)
        self.one_action.setToolTip("1:1: one pixel of the display on one pixel of the screen (Ctrl+Alt+1)")
        self.one_action.triggered.connect(self.one_to_one)
        self.toolbar.addAction(self.one_action)
        self.full_action = QAction(_icon(_draw_full_screen, palette), "Full screen", self)
        self.full_action.setToolTip("Full screen (Ctrl+Alt+F or F11; the same keys come back)")
        self.full_action.triggered.connect(self.toggle_full_screen)
        self.toolbar.addAction(self.full_action)
        self.remote_window = None
        if self.keys_on:
            self.remote_window = RemoteControlWindow(sender, self.key_event)
            self.remote_action = QAction(_icon(_draw_remote, palette), "Remote control", self)
            self.remote_action.setToolTip("Show or hide the on-screen remote control (Ctrl+Alt+R)")
            self.remote_action.setCheckable(True)
            self.remote_action.triggered.connect(self.show_remote)
            self.remote_window.closed.connect(lambda: self.remote_action.setChecked(False))
            self.toolbar.addAction(self.remote_action)
        self.refresh_sound()
        self.client.start()
        if args.fullscreen:
            self.toggle_full_screen()
        if args.remote_control == "window":
            QTimer.singleShot(0, lambda: self.show_remote(True))

    # ----------------------------------------------------------- display

    def on_size(self, width, height):
        self.display.on_size(width, height)
        self.note_cut(width, height)
        # As large as 1:1, or as the screen allows: when the display's size
        # is first known, and when it changes (a VM's display has another
        # size until the target sets its own), unless the user has given the
        # window a size since.
        if not self.isFullScreen() and (self.fitted is None or self.fitted == self.size()):
            self.one_to_one()
            self.fitted = self.size()

    def note_cut(self, width, height):
        """Say so, once, when the display server gives only the top left part
        of the target's display. QEMU 8.2's stops at 2560x2048, so of a 4K
        display it serves that much; QEMU 11 serves all of it."""
        expected = getattr(self.args, "expect", None)
        if not expected or self.cut_noted or (width, height) == expected:
            return
        if (width, height) == (min(expected[0], VNC_LIMIT[0]), min(expected[1], VNC_LIMIT[1])):
            self.cut_noted = True
            print("emu: the window shows the top left %dx%d of the target's %dx%d display: this QEMU's display "
                  "server gives no more. --option window=qemu shows all of it, in QEMU's own window (no toolbar, "
                  "no remote control keys)" % (width, height, expected[0], expected[1]), file=sys.stderr, flush=True)

    def one_to_one(self):
        if self.isFullScreen():
            self.toggle_full_screen()
        wanted = self.display.natural_size()
        frame = self.size() - self.display.size()
        available = self.screen().availableGeometry().size() - frame - QSize(0, 40)
        if wanted.width() > available.width() or wanted.height() > available.height():
            wanted = wanted.scaled(available, Qt.AspectRatioMode.KeepAspectRatio)
        self.resize(wanted + frame)

    def toggle_full_screen(self):
        if self.isFullScreen():
            self.showNormal()
            self.toolbar.show()
        else:
            self.toolbar.hide()
            self.showFullScreen()

    def show_remote(self, shown):
        if self.remote_window is None:
            return
        self.remote_action.setChecked(bool(shown))
        if shown:
            place = self.frameGeometry().topRight() + QPoint(12, 0)
            if not self.screen().availableGeometry().contains(place + QPoint(self.remote_window.width(), 0)):
                place = self.frameGeometry().topLeft() + QPoint(24, 48)
            self.remote_window.move(place)
            self.remote_window.show()
        else:
            self.remote_window.hide()

    # ------------------------------------------------------------- sound

    def refresh_sound(self):
        """Ask the run's audio process whether it is muted; without one the
        run plays no sound and the button is off."""
        self.muted = None
        if self.audio_port:
            try:
                self.muted = bool(hostaudio.control(self.audio_port, "status", timeout=2)["muted"])
            except (OSError, ValueError, KeyError):
                self.muted = None
        self.mute_action.setEnabled(self.muted is not None)
        self.mute_action.setChecked(bool(self.muted))
        self.mute_action.setIcon(self.sound_icons[bool(self.muted)])
        self.mute_action.setToolTip(
            "This run plays no sound through the host" if self.muted is None else
            "Sound is muted: turn it on (Ctrl+Alt+M)" if self.muted else "Mute the sound (Ctrl+Alt+M)")

    def set_muted(self, muted):
        if self.audio_port:
            try:
                hostaudio.control(self.audio_port, "mute" if muted else "unmute", timeout=2)
            except (OSError, ValueError):
                pass
        self.refresh_sound()

    # -------------------------------------------------------------- keys

    def key_event(self, event, pressed):
        """A key of the host keyboard, in this window or in the remote
        control's. Returns whether it was used."""
        key = event.key()
        modifiers = event.modifiers()
        if pressed and not event.isAutoRepeat():
            command = bool(modifiers & COMMAND_KEYS) and bool(modifiers & Qt.KeyboardModifier.AltModifier)
            if key == Qt.Key.Key_F11.value or (command and key == Qt.Key.Key_F.value):
                self.toggle_full_screen()
                return True
            if command and key == Qt.Key.Key_M.value:
                if self.mute_action.isEnabled():
                    self.set_muted(not self.muted)
                return True
            if command and key == Qt.Key.Key_1.value:
                self.one_to_one()
                return True
            if command and key == Qt.Key.Key_R.value:
                if self.remote_window is not None:
                    self.show_remote(not self.remote_window.isVisible())
                return True
        if not self.keys_on or self.sender is None:
            return False
        name = host_key_name(key)
        if pressed:
            if modifiers & (COMMAND_KEYS | Qt.KeyboardModifier.AltModifier):
                return False
            code = remote.CODES.get(remote.HOST_KEYS.get(name))
            if code is None:
                return False
            if not event.isAutoRepeat():        # the target repeats a held key itself
                self.pressed[name] = code
                self.sender.press(code)
            return True
        code = self.pressed.pop(name, None)
        if code is None or event.isAutoRepeat():
            return False
        self.sender.release(code)
        return True

    def keyPressEvent(self, event):
        if not self.key_event(event, True):
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if not self.key_event(event, False):
            super().keyReleaseEvent(event)

    def closeEvent(self, event):
        for code in self.pressed.values():
            self.sender.release(code)
        self.client.close()
        if self.remote_window is not None:
            self.remote_window.close()
        super().closeEvent(event)
        QApplication.instance().quit()


# ---------------------------------------------------------------- control ---

class Control(QObject):
    """Commands for the window as JSON lines on standard input, each answered
    with one JSON line. For the launcher's checks, which have to see what the
    window shows and to press its keys as a person would."""
    line = Signal(str)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.line.connect(self.run)
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for text in sys.stdin:
            if text.strip():
                self.line.emit(text)
        self.line.emit('{"do": "quit"}')

    def answer(self, data):
        print(json.dumps(data), flush=True)

    def run(self, text):
        from PySide6.QtTest import QTest
        window = self.window
        try:
            command = json.loads(text)
            what = command.get("do")
            if what == "state":
                width, height = window.display.display_size()
                natural = window.display.natural_size()
                shown = window.display.shown_rect()
                self.answer({
                    "connected": window.client.connected, "updates": window.client.updates,
                    "display": [width, height] if window.display.image is not None else None,
                    "widget": [window.display.width(), window.display.height()],
                    "shown": [shown.width(), shown.height()],
                    "natural": [natural.width(), natural.height()],
                    "pixel_ratio": window.display.devicePixelRatioF(),
                    "full_screen": window.isFullScreen(), "toolbar": window.toolbar.isVisible(),
                    "active": window.isActiveWindow(),
                    "screen": [window.screen().geometry().width(), window.screen().geometry().height()],
                    "window": [window.width(), window.height()],
                    "muted": window.muted, "visible": window.isVisible(),
                    "remote_window": bool(window.remote_window is not None and window.remote_window.isVisible()),
                    "remote_buttons": sorted(window.remote_window.buttons) if window.remote_window else []})
            elif what == "save-display":
                # What arrived from the target, pixel for pixel.
                ok = window.display.image is not None and window.display.image.save(command["path"])
                self.answer({"saved": bool(ok)})
            elif what == "save-window":
                # What the window draws: the display as it is scaled, and the toolbar.
                self.answer({"saved": bool(window.grab().save(command["path"]))})
            elif what == "save-shown":
                # The part of the window that shows the display.
                picture = window.display.grab(window.display.shown_rect())
                self.answer({"saved": bool(picture.save(command["path"])),
                             "size": [picture.width(), picture.height()],
                             "pixel_ratio": picture.devicePixelRatioF()})
            elif what == "save-remote":
                self.answer({"saved": bool(window.remote_window.grab().save(command["path"]))})
            elif what == "resize":
                window.resize(window.size() - window.display.size() + QSize(*command["display"]))
                self.answer({"ok": True})
            elif what == "host-key":
                # A key of the host keyboard, typed into the display.
                key = qt_key(command["key"])
                modifiers = Qt.KeyboardModifier.NoModifier
                for name in command.get("with", []):
                    modifiers |= {"ctrl": Qt.KeyboardModifier.ControlModifier, "alt": Qt.KeyboardModifier.AltModifier,
                                  "meta": Qt.KeyboardModifier.MetaModifier}[name]
                target = window.remote_window if command.get("in") == "remote" else window.display
                QTest.keyClick(target, Qt.Key(key), modifiers)
                self.answer({"ok": True})
            elif what == "remote-click":
                # A mouse click on a button of the on-screen remote control.
                button = window.remote_window.buttons[command["key"]]
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                self.answer({"ok": True})
            elif what == "toolbar":
                {"mute": window.mute_action, "one-to-one": window.one_action, "full-screen": window.full_action,
                 "remote": getattr(window, "remote_action", None)}[command["action"]].trigger()
                self.answer({"ok": True})
            elif what == "send-key":
                # Straight to the target, past the window: ends the remote-keys workload.
                window.sender.tap(int(command["code"]))
                self.answer({"ok": True})
            elif what == "quit":
                self.answer({"ok": True})
                window.close()
            else:
                self.answer({"error": "unknown command %r" % what})
        except Exception as error:      # a check must get an answer, whatever went wrong
            self.answer({"error": "%s: %s" % (type(error).__name__, error)})


def _size(text):
    width, _, height = text.partition("x")
    return int(width), int(height)


def _address(text):
    host, separator, port = text.rpartition(":")
    if separator and port.isdigit() and "/" not in text and "\\" not in text:
        return (host or "127.0.0.1", int(port))
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(prog="emulator.gui.viewer", description=__doc__.splitlines()[0])
    parser.add_argument("--display", required=True, type=_address, metavar="ADDRESS")
    parser.add_argument("--title", default="Emulator")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--remote-control", choices=("keys", "window"))
    parser.add_argument("--keys-exec", type=json.loads, metavar="JSON")
    parser.add_argument("--keys-listen", type=int, metavar="PORT")
    parser.add_argument("--audio-control", type=int, metavar="PORT")
    parser.add_argument("--control", action="store_true")
    parser.add_argument("--expect", type=_size, metavar="WIDTHxHEIGHT",
                        help="the size of the target's display, to tell a display server that serves less of it")
    args = parser.parse_args(argv)

    sender = None
    if args.keys_exec:
        sender = remote.ExecSender(args.keys_exec)
    elif args.keys_listen:
        sender = remote.ListenSender(args.keys_listen)
    if sender is None:
        args.remote_control = None
    application = QApplication(sys.argv[:1])
    application.setApplicationName("Emulator")
    window = Window(args, sender)
    window.show()
    window.raise_()
    window.activateWindow()
    control = Control(window) if args.control else None
    status = application.exec()
    if sender is not None:
        sender.close()
    del control
    return status


if __name__ == "__main__":
    sys.exit(main())
