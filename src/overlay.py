"""Right Shift overlay: a separate always-on-top window over Roblox (no injection).
Only opens when Right Shift is tapped on its own, so typing capitals in chat doesn't trigger it."""
import ctypes
import os

from PySide6.QtCore import QObject, QRect, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

import config
from widgets import ghost, label

VK_RSHIFT = 0xA1
IGNORE = {0x10, 0xA0, 0xA1}          # shift keys themselves
DEFAULT_URL = "https://www.eldorado.gg/"


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


class Overlay(QWidget):
    def __init__(self, cfg, clicker):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.cfg = cfg
        self.clicker = clicker
        self.roblox_hwnd = None
        self.view = None
        # opaque window (web views + see-through windows don't mix); Windows 11 rounds the corners for us
        self.setWindowTitle("Chrome Blox overlay")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame()
        self.panel.setProperty("overlay", True)
        outer.addWidget(self.panel)
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(label(config.APP_NAME, "brand"))
        self.now = label("", "pill")
        self.now.hide()
        bar.addWidget(self.now)
        bar.addStretch(1)
        self.btn_back = ghost(QPushButton("‹"))
        self.btn_fwd = ghost(QPushButton("›"))
        self.btn_reload = ghost(QPushButton("Reload"))
        self.btn_home = ghost(QPushButton("Home"))
        for b in (self.btn_back, self.btn_fwd):
            b.setFixedWidth(40)
        close = QPushButton("Close  (Right Shift)")
        close.clicked.connect(self.close_overlay)
        for b in (self.btn_back, self.btn_fwd, self.btn_reload, self.btn_home, close):
            bar.addWidget(b)
        lay.addLayout(bar)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.placeholder = label("Loading…", "muted")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.placeholder, 1)
        lay.addLayout(self.body, 1)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close_overlay)

    # ---------- web view (made the first time you open it)
    def _ensure_view(self):
        if self.view is not None:
            return
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView
        # its own saved profile, so sites you sign into here stay signed in
        self.profile = QWebEngineProfile("overlay", QApplication.instance())
        web = config.BASE / "web"
        self.profile.setPersistentStoragePath(str(web / "storage"))
        self.profile.setCachePath(str(web / "cache"))
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.view = QWebEngineView(self.panel)
        self.view.setPage(QWebEnginePage(self.profile, self.view))
        self.body.removeWidget(self.placeholder)
        self.placeholder.deleteLater()
        self.body.addWidget(self.view, 1)
        self.btn_back.clicked.connect(self.view.back)
        self.btn_fwd.clicked.connect(self.view.forward)
        self.btn_reload.clicked.connect(self.view.reload)
        self.btn_home.clicked.connect(lambda: self.view.load(QUrl(self.home_url())))
        self.view.load(QUrl(self.home_url()))

    def home_url(self):
        url = (self.cfg.get("overlay_url") or DEFAULT_URL).strip()
        return url if url.startswith(("http://", "https://")) else "https://" + url

    # ---------- show / hide
    def set_game(self, name):
        self.now.setText(f"Playing {name}" if name else "")
        self.now.setVisible(bool(name))

    def toggle(self, hwnd=None):
        if self.isVisible():
            self.close_overlay()
        else:
            self.open_overlay(hwnd)

    def open_overlay(self, hwnd=None):
        self.roblox_hwnd = hwnd
        if hwnd:
            area = window_rect(hwnd)
        else:
            area = QGuiApplication.primaryScreen().availableGeometry()
        w, h = int(area.width() * 0.78), int(area.height() * 0.82)
        self.setGeometry(area.x() + (area.width() - w) // 2, area.y() + (area.height() - h) // 2, w, h)
        self.clicker.play()
        self.show()
        self._round_corners()
        self.raise_()
        self.activateWindow()
        self._ensure_view()

    def _round_corners(self):
        if os.name != "nt":
            return
        try:
            pref = ctypes.c_int(2)   # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 33, ctypes.byref(pref), 4)
        except Exception:
            pass

    def close_overlay(self):
        if not self.isVisible():
            return
        self.hide()
        if self.roblox_hwnd and os.name == "nt":
            _user32().SetForegroundWindow(self.roblox_hwnd)   # straight back into the game
