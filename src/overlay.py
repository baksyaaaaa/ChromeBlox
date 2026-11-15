"""Right Shift quick menu: a separate always-on-top window over Roblox (no injection).
Only opens when Right Shift is tapped on its own, so typing capitals in chat doesn't trigger it."""
import ctypes
import os
import time

from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

import config
from widgets import card, ghost, label, rounded

VK_RSHIFT = 0xA1
IGNORE = {0x10, 0xA0, 0xA1}          # shift keys themselves


def _user32():
    return ctypes.windll.user32 if os.name == "nt" else None


def _window_title(hwnd):
    u = _user32()
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def roblox_window():
    """The Roblox window handle if it's the active window, else None."""
    u = _user32()
    if not u:
        return None
    hwnd = u.GetForegroundWindow()
    return hwnd if hwnd and _window_title(hwnd) == "Roblox" else None


def window_rect(hwnd):
    from ctypes import wintypes
    r = wintypes.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(r))
    return QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)


class RightShiftWatcher(QObject):
    """Polls the keyboard (no hooks). Fires when Right Shift is pressed and released with no other key."""
    tapped = Signal(object)          # Roblox hwnd, or None when the overlay itself was focused

    def __init__(self, overlay_visible):
        super().__init__()
        self.overlay_visible = overlay_visible
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self._poll)
        self.held = False
        self.dirty = False
        self.hwnd = None

    def start(self):
        if os.name == "nt":
            self.timer.start()

    def stop(self):
        self.timer.stop()

    def _poll(self):
        u = _user32()
        down = bool(u.GetAsyncKeyState(VK_RSHIFT) & 0x8000)
        if down and not self.held:
            self.hwnd = roblox_window()
            if self.hwnd or self.overlay_visible():
                self.held, self.dirty = True, False
            return
        if self.held and down:
            for vk in range(0x01, 0xFF):
                if vk not in IGNORE and u.GetAsyncKeyState(vk) & 0x8000:
                    self.dirty = True
                    break
            return
        if self.held and not down:
            self.held = False
            if not self.dirty:
                self.tapped.emit(self.hwnd)


def fmt_time(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class Overlay(QWidget):
    def __init__(self, host):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.host = host
        self.game = None
        self.roblox_hwnd = None
        self.setWindowTitle("Chrome Blox menu")
        self.setFixedSize(620, 262)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setProperty("overlay", True)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(14)

        bar = QHBoxLayout()
        bar.addWidget(label(config.APP_NAME, "brand"))
        bar.addStretch(1)
        hint = label("Right Shift / Esc to close", "muted")
        hint.setWordWrap(False)
        bar.addWidget(hint)
        lay.addLayout(bar)

        c, cl = card((16, 14, 16, 14))
        top = QHBoxLayout()
        top.setSpacing(14)
        self.icon = QLabel()
        self.icon.setObjectName("gamebig")
        self.icon.setFixedSize(72, 72)
        top.addWidget(self.icon)
        info = QVBoxLayout()
        info.setSpacing(4)
        self.name = label("Not in a game", "h2")
        self.name.setStyleSheet("font-size: 18px;")
        self.by = label("Join a game and it shows up here.", "muted")
        pills = QHBoxLayout()
        pills.setSpacing(6)
        self.region = label("", "pill")
        self.timer_lbl = label("", "stat")
        pills.addWidget(self.region)
        pills.addWidget(self.timer_lbl)
        pills.addStretch(1)
        info.addWidget(self.name)
        info.addWidget(self.by)
        info.addLayout(pills)
        top.addLayout(info, 1)
        cl.addLayout(top)
        lay.addWidget(c)

        acts = QHBoxLayout()
        acts.setSpacing(8)
        self.b_rejoin = QPushButton("Rejoin server")
        self.b_rejoin.clicked.connect(self._rejoin)
        self.b_invite = QPushButton("Copy invite link")
        self.b_invite.clicked.connect(self._copy_invite)
        self.b_better = QPushButton("Find a better server")
        self.b_better.clicked.connect(self._better)
        self.b_leave = ghost(QPushButton("Leave game"))
        self.b_leave.clicked.connect(self._leave)
        for b in (self.b_rejoin, self.b_invite, self.b_better, self.b_leave):
            acts.addWidget(b)
        lay.addLayout(acts)
        self.msg = label("", "muted")
        lay.addWidget(self.msg)
        lay.addStretch(1)

        self.tick = QTimer(self)
        self.tick.setInterval(1000)
        self.tick.timeout.connect(self._update_timer)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close_overlay)
        self.set_game(None)

    # ---------- data
    def set_game(self, g):
        self.game = g or None
        has = bool(self.game and self.game.get("place_id"))
        if has:
            self.name.setText(self.game.get("name") or "Roblox")
            self.by.setText(f"by {self.game['creator']}" if self.game.get("creator") else "")
            self.region.setText(f"Server: {self.game['region']}" if self.game.get("region") else "Server: finding…")
            pm = QPixmap()
            if self.game.get("icon") and pm.loadFromData(self.game["icon"]):
                self.icon.setPixmap(rounded(pm, 72, radius=12))
        else:
            self.name.setText("Not in a game")
            self.by.setText("Join a game and it shows up here.")
            self.icon.clear()
        self.region.setVisible(has)
        self.timer_lbl.setVisible(has)
        for b in (self.b_rejoin, self.b_invite, self.b_better):
            b.setEnabled(has)
        self.b_leave.setEnabled(self.host.roblox_running())
        self._update_timer()

    def _update_timer(self):
        if self.game and self.game.get("joined_at"):
            self.timer_lbl.setText(f"In server {fmt_time(time.time() - self.game['joined_at'])}")

    # ---------- actions
    def _rejoin(self):
        g = self.game
        uri = f"roblox://experiences/start?placeId={g['place_id']}"
        if g.get("job_id"):
            uri += f"&gameInstanceId={g['job_id']}"
        self.close_overlay(refocus=False)
        self.host.start_launch(uri)

    def _copy_invite(self):
        g = self.game
        link = f"https://www.roblox.com/games/start?placeId={g['place_id']}"
        if g.get("job_id"):
            link += f"&gameInstanceId={g['job_id']}"
        QGuiApplication.clipboard().setText(link)
        self.msg.setText("Invite link copied. Friends who open it join your exact server.")

    def _better(self):
        pid = self.game["place_id"]
        self.close_overlay(refocus=False)
        self.host._restore()
        self.host.srv_sort.setCurrentText("Best ping")
        self.host._srv_open(pid)

    def _leave(self):
        self.close_overlay(refocus=False)
        self.host.close_roblox()

    # ---------- show / hide
    def toggle(self, hwnd=None):
        if self.isVisible():
            self.close_overlay()
        else:
            self.open_overlay(hwnd)

    def open_overlay(self, hwnd=None):
        self.roblox_hwnd = hwnd
        area = window_rect(hwnd) if hwnd else QGuiApplication.primaryScreen().availableGeometry()
        self.move(area.x() + (area.width() - self.width()) // 2, area.y() + (area.height() - self.height()) // 2)
        self.msg.setText("")
        self.set_game(self.game)
        self.host.clicker.play()
        self.show()
        self._round_corners()
        self.raise_()
        self.activateWindow()
        self.tick.start()

    def _round_corners(self):
        if os.name != "nt":
            return
        try:
            pref = ctypes.c_int(2)   # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 33, ctypes.byref(pref), 4)
        except Exception:
            pass

    def close_overlay(self, refocus=True):
        if not self.isVisible():
            return
        self.tick.stop()
        self.hide()
        if refocus and self.roblox_hwnd and os.name == "nt":
            _user32().SetForegroundWindow(self.roblox_hwnd)   # straight back into the game
