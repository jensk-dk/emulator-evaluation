"""The on-screen remote control: a window that shows a TV remote control
whose buttons are clicked with the mouse.

It has a button for every remote control key (emulator/remote.py). A button
is held for as long as the mouse button is, as on a real one. The host keys
that stand for remote control keys work in this window too.
"""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QPushButton, QWidget

from .. import remote

WIDTH, HEIGHT = 232, 548
COLUMNS = (20, 88, 156)             # three buttons across
QUARTERS = (20, 70, 120, 170)       # four across

# key -> (x, y, width, height, kind)
LAYOUT = {
    "text": (COLUMNS[0], 46, 56, 28, "pill"), "webtv": (COLUMNS[1], 46, 56, 28, "pill"),
    "exit": (COLUMNS[2], 46, 56, 28, "pill"),
    "1": (COLUMNS[0], 90, 56, 30, "key"), "2": (COLUMNS[1], 90, 56, 30, "key"), "3": (COLUMNS[2], 90, 56, 30, "key"),
    "4": (COLUMNS[0], 126, 56, 30, "key"), "5": (COLUMNS[1], 126, 56, 30, "key"), "6": (COLUMNS[2], 126, 56, 30, "key"),
    "7": (COLUMNS[0], 162, 56, 30, "key"), "8": (COLUMNS[1], 162, 56, 30, "key"), "9": (COLUMNS[2], 162, 56, 30, "key"),
    "channel_down": (COLUMNS[0], 198, 56, 30, "key"), "0": (COLUMNS[1], 198, 56, 30, "key"),
    "channel_up": (COLUMNS[2], 198, 56, 30, "key"),
    "up": (COLUMNS[1], 246, 56, 40, "pad"),
    "left": (COLUMNS[0], 290, 56, 40, "pad"), "ok": (COLUMNS[1], 290, 56, 40, "ok"),
    "right": (COLUMNS[2], 290, 56, 40, "pad"),
    "back": (COLUMNS[0], 334, 56, 40, "pill"), "down": (COLUMNS[1], 334, 56, 40, "pad"),
    "red": (QUARTERS[0], 392, 42, 22, "red"), "green": (QUARTERS[1], 392, 42, 22, "green"),
    "yellow": (QUARTERS[2], 392, 42, 22, "yellow"), "blue": (QUARTERS[3], 392, 42, 22, "blue"),
    "rewind": (QUARTERS[0], 430, 42, 30, "key"), "play": (QUARTERS[1], 430, 42, 30, "key"),
    "pause": (QUARTERS[2], 430, 42, 30, "key"), "fast_forward": (QUARTERS[3], 430, 42, 30, "key"),
    "stop": (COLUMNS[0], 468, 56, 30, "key"), "play_pause": (COLUMNS[1], 468, 56, 30, "key"),
    "record": (COLUMNS[2], 468, 56, 30, "key"),
}
TEXTS = {"text": "TEXT", "webtv": "WEB", "exit": "EXIT", "back": "BACK", "ok": "OK", "channel_up": "P+",
         "channel_down": "P−"}
COLOURS = {"red": "#d6342c", "green": "#2f9e44", "yellow": "#e8b90c", "blue": "#2f6fd6"}
STYLE = """
QPushButton { color: #f2f2f2; background: #3b3e45; border: 1px solid #17181b; border-radius: %(radius)dpx;
              font-size: %(font)dpx; font-weight: 600; }
QPushButton:hover { background: #4a4e57; }
QPushButton:pressed { background: #6a707c; }
"""


def _glyph(key):
    """The sign on a button that has no words: an arrow or a playback sign."""
    icon = QIcon()
    for scale in (1, 2):
        pixmap = QPixmap(22 * scale, 16 * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(scale, scale)
        colour = QColor("#e23b33") if key == "record" else QColor("#f2f2f2")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)

        def triangle(x, direction=1, width=7):
            painter.drawPolygon(QPolygonF([QPointF(x, 3), QPointF(x + direction * width, 8), QPointF(x, 13)]))

        def bar(x, width=2.4):
            painter.drawRect(QRectF(x, 3, width, 10))

        if key == "up":
            painter.drawPolygon(QPolygonF([QPointF(5, 12), QPointF(11, 4), QPointF(17, 12)]))
        elif key == "down":
            painter.drawPolygon(QPolygonF([QPointF(5, 4), QPointF(11, 12), QPointF(17, 4)]))
        elif key == "left":
            triangle(15, -1, 8)
        elif key == "right":
            triangle(7, 1, 8)
        elif key == "play":
            triangle(7, 1, 9)
        elif key == "pause":
            bar(6.5)
            bar(13)
        elif key == "play_pause":
            triangle(3, 1, 7)
            bar(12.5, 2)
            bar(16.5, 2)
        elif key == "stop":
            painter.drawRect(QRectF(6.5, 3.5, 9, 9))
        elif key == "record":
            painter.drawEllipse(QPointF(11, 8), 4.6, 4.6)
        elif key == "fast_forward":
            triangle(4, 1, 7)
            triangle(11, 1, 7)
        elif key == "rewind":
            triangle(11, -1, 7)
            triangle(18, -1, 7)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class RemoteControlWindow(QWidget):
    closed = Signal()

    def __init__(self, sender, key_event):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.sender = sender
        self.key_event = key_event          # the display window's handling of host keys
        self.buttons = {}
        self.setWindowTitle("Remote control")
        self.setFixedSize(WIDTH, HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for key, label, code, _ in remote.KEYS:
            x, y, width, height, kind = LAYOUT[key]
            button = QPushButton(self)
            button.setObjectName(key)
            button.setGeometry(x, y, width, height)
            # The keyboard stays with the window, so host keys keep working.
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            radius = height // 2 if kind in ("pill", "ok", "red", "green", "yellow", "blue") else 8
            style = STYLE % {"radius": radius, "font": 13 if kind in ("key", "ok") else 11}
            if kind in COLOURS:
                style += "QPushButton { background: %s; } QPushButton:hover { background: %s; }" \
                         % (COLOURS[kind], QColor(COLOURS[kind]).lighter(118).name())
                style += "QPushButton:pressed { background: %s; }" % QColor(COLOURS[kind]).darker(130).name()
            button.setStyleSheet(style)
            if key in TEXTS or key.isdigit():
                button.setText(TEXTS.get(key, key))
            elif kind not in COLOURS:
                button.setIcon(_glyph(key))
                button.setIconSize(QSize(22, 16))
            hosts = ", ".join(remote.host_keys_of(key))
            button.setToolTip("%s (%s on the keyboard)" % (label, hosts))
            button.setAccessibleName(label)
            button.pressed.connect(lambda code=code: self.sender.press(code))
            button.released.connect(lambda code=code: self.sender.release(code))
            self.buttons[key] = button

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f1012"))
        body = QRectF(6, 6, WIDTH - 12, HEIGHT - 12)
        shade = QLinearGradient(0, 0, WIDTH, 0)
        shade.setColorAt(0.0, QColor("#2c2e33"))
        shade.setColorAt(0.5, QColor("#24262a"))
        shade.setColorAt(1.0, QColor("#1b1c1f"))
        painter.setBrush(shade)
        painter.setPen(QPen(QColor("#050506"), 1.5))
        painter.drawRoundedRect(body, 26, 26)
        # The window the infrared light leaves a real one through.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#4a1418"))
        painter.drawRoundedRect(QRectF(WIDTH / 2 - 22, 18, 44, 10), 5, 5)
        # The ring the arrow keys sit on.
        painter.setBrush(QColor("#17181b"))
        painter.drawRoundedRect(QRectF(14, 240, WIDTH - 28, 140), 22, 22)
        painter.setPen(QColor("#6d717a"))
        font = QFont(painter.font())
        font.setPixelSize(10)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        painter.setFont(font)
        painter.drawText(QRectF(0, HEIGHT - 40, WIDTH, 16), Qt.AlignmentFlag.AlignCenter, "EMU REMOTE")
        painter.end()

    def keyPressEvent(self, event):
        if not self.key_event(event, True):
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if not self.key_event(event, False):
            super().keyReleaseEvent(event)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
