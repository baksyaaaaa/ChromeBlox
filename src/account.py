"""Roblox sign-in: you log in on roblox.com inside the launcher, the session is kept
encrypted with Windows (DPAPI) so only your Windows account on this PC can read it."""
import ctypes
import os

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout

import config

SESSION_FILE = config.BASE / "session.bin"


# ---------------------------------------------------------------- DPAPI
if os.name == "nt":
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _crypt(data, protect):
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
        if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            raise OSError("DPAPI failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def save_session(cookie):
    if os.name != "nt":
        return  # only kept in memory off Windows
    SESSION_FILE.write_bytes(_crypt(cookie.encode("utf-8"), True))


def load_session():
    if os.name != "nt" or not SESSION_FILE.exists():
        return None
    try:
        return _crypt(SESSION_FILE.read_bytes(), False).decode("utf-8")
    except Exception:
        return None


def clear_session():
    SESSION_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------- login window
_profile = None


class LoginDialog(QDialog):
    """roblox.com login page. You type everything yourself; we only pick up the session cookie at the end."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView
        global _profile
        if _profile is None:
            _profile = QWebEngineProfile(QApplication.instance())   # off the record: nothing saved by Qt
        self.cookie = None
        self.setWindowTitle("Sign in to Roblox")
        self.resize(480, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView(self)
        self.page = QWebEnginePage(_profile, self.view)
        self.view.setPage(self.page)
        lay.addWidget(self.view)
        _profile.cookieStore().cookieAdded.connect(self._cookie)
        _profile.cookieStore().deleteAllCookies()
        self.view.load(QUrl("https://www.roblox.com/login"))

    def _cookie(self, c):
        try:
            if bytes(c.name()).decode() == ".ROBLOSECURITY":
                val = bytes(c.value()).decode()
                if val and not self.cookie:
                    self.cookie = val
                    QTimer.singleShot(400, self.accept)
        except Exception:
            pass

    def done(self, r):
        try:
            _profile.cookieStore().cookieAdded.disconnect(self._cookie)
        except Exception:
            pass
        super().done(r)
