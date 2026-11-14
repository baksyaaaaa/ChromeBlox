import json
import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QThread, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSlider, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

import config
import mods
import presence
import roblox
from sound import CUSTOM as CUSTOM_SOUND, Clicker


# ---------------------------------------------------------------- helpers
def scrub(text):
    """Never show your Windows username / folder paths on screen."""
    text = str(text).replace(str(Path.home()), "~")
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if user and len(user) > 2:
        text = text.replace(user, "user")
    return text


def rgba(hex_color, a):
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{a})"


def make_icon(accent):
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(accent))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", 30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "C")
    p.end()
    return QIcon(pm)


def stylesheet(cfg):
    acc, bg = cfg["accent"], cfg["background"]
    return f"""
    QWidget {{ color: #ecebf2; font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; }}
    #Sidebar {{ background: rgba(0,0,0,0.28); border-right: 1px solid rgba(255,255,255,0.06); }}
    #Logo {{ font-size: 17px; font-weight: 700; padding: 6px 4px 14px 4px; }}
    QPushButton {{ background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.15);
                   border-radius: 6px; padding: 8px 14px; }}
    QPushButton:hover {{ background: rgba(255,255,255,0.12); }}
    QPushButton:pressed {{ background: rgba(255,255,255,0.04); }}
    QPushButton:disabled {{ color: rgba(255,255,255,0.35); }}
    QPushButton#Nav {{ text-align: left; padding: 10px 14px; background: rgba(255,255,255,0.03);
                       border: 1px solid rgba(255,255,255,0.05); }}
    QPushButton#Nav:checked {{ background: {rgba(acc, 0.18)}; border: 1px solid {rgba(acc, 0.45)}; }}
    QPushButton#Play {{ background: {rgba(acc, 0.28)}; border: 1px solid {rgba(acc, 0.65)};
                        font-size: 18px; font-weight: 600; padding: 14px 46px; }}
    QPushButton#Play:hover {{ background: {rgba(acc, 0.40)}; }}
    QPushButton#Swatch {{ min-width: 60px; }}
    QLineEdit, QPlainTextEdit, QComboBox {{ background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; padding: 7px;
        selection-background-color: {acc}; }}
    QPlainTextEdit {{ font-family: 'Cascadia Mono', 'Consolas', monospace; }}
    QComboBox QAbstractItemView {{ background: {bg}; border: 1px solid rgba(255,255,255,0.12); }}
    QProgressBar {{ background: rgba(255,255,255,0.07); border: none; border-radius: 3px; }}
    QProgressBar::chunk {{ background: {acc}; border-radius: 3px; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid rgba(255,255,255,0.3); background: rgba(255,255,255,0.05); }}
    QCheckBox::indicator:checked {{ background: {acc}; border-color: {acc}; }}
    QSlider::groove:horizontal {{ height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {acc}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; border-radius: 7px; background: #ecebf2; }}
    #Card {{ background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; }}
    #H1 {{ font-size: 28px; font-weight: 700; }}
    #H2 {{ font-size: 15px; font-weight: 600; }}
    #Muted {{ color: rgba(236,235,242,0.55); }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.15); border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QMenu {{ background: {bg}; border: 1px solid rgba(255,255,255,0.12); }}
    QMenu::item:selected {{ background: {rgba(acc, 0.3)}; }}
    """


def card(title=None, text=None):
    f = QFrame()
    f.setObjectName("Card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)
    if title:
        t = QLabel(title)
        t.setObjectName("H2")
        lay.addWidget(t)
    if text:
        m = QLabel(text)
        m.setObjectName("Muted")
        m.setWordWrap(True)
        lay.addWidget(m)
    return f, lay


def row(*widgets, stretch=True):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for x in widgets:
        lay.addWidget(x)
    if stretch:
        lay.addStretch(1)
    return w


# ---------------------------------------------------------------- background
class Root(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self._pix = None
        self.reload()

    def reload(self):
        p = self.cfg.get("bg_image")
        self._pix = QPixmap(p) if p and Path(p).is_file() else None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self.cfg["background"]))
        if self._pix and not self._pix.isNull():
            s = self._pix.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(0, 0, s, (s.width() - self.width()) // 2, (s.height() - self.height()) // 2,
                         self.width(), self.height())
            p.fillRect(self.rect(), QColor(0, 0, 0, 150))


# ---------------------------------------------------------------- worker
class LaunchWorker(QObject):
    status = Signal(str)
    progress = Signal(int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, cfg, uri, launch=True):
        super().__init__()
        self.cfg, self.uri, self.launch = cfg, uri, launch

    def run(self):
        try:
            self.status.emit("Checking for Roblox updates…")
            try:
                version = roblox.latest_version()
            except Exception:
                version = self.cfg.get("current_version")
                if not roblox.is_installed(version):
                    raise RuntimeError("Can't reach Roblox and nothing is installed yet. Check your internet.")
                self.status.emit("Offline, using the installed version")
            folder = roblox.install(version, self.progress.emit, self.status.emit)
            if self.cfg.get("current_version") != version:
                self.cfg["current_version"] = version
                self.cfg.save()
                roblox.cleanup_old(version)
            if not self.launch:
                self.done.emit(None)
                return
            self.status.emit("Applying mods…")
            mods.apply_mods(folder, self.cfg)
            self.status.emit("Starting Roblox…")
            self.done.emit(roblox.launch(folder, self.uri, self.cfg.get("multi_instance", False)))
        except Exception as e:
            self.failed.emit(scrub(e))


# ---------------------------------------------------------------- fast flag presets
FLAG_PRESETS = {
    "Graphics API": {
        "Automatic": {},
        "Direct3D 11": {"FFlagDebugGraphicsPreferD3D11": "True"},
        "Vulkan": {"FFlagDebugGraphicsPreferVulkan": "True"},
        "OpenGL": {"FFlagDebugGraphicsPreferOpenGL": "True"},
    },
    "Anti-aliasing (MSAA)": {
        "Automatic": {},
        "Off": {"FIntDebugForceMSAASamples": "0"},
        "1x": {"FIntDebugForceMSAASamples": "1"},
        "2x": {"FIntDebugForceMSAASamples": "2"},
        "4x": {"FIntDebugForceMSAASamples": "4"},
        "8x": {"FIntDebugForceMSAASamples": "8"},
    },
    "Texture quality": {
        "Automatic": {},
        "Lowest": {"DFFlagTextureQualityOverrideEnabled": "True", "DFIntTextureQualityOverride": "0"},
        "Low": {"DFFlagTextureQualityOverrideEnabled": "True", "DFIntTextureQualityOverride": "1"},
        "Medium": {"DFFlagTextureQualityOverrideEnabled": "True", "DFIntTextureQualityOverride": "2"},
        "High": {"DFFlagTextureQualityOverrideEnabled": "True", "DFIntTextureQualityOverride": "3"},
    },
}


# ---------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self, cfg, launch_uri=None):
        super().__init__()
        self.cfg = cfg
        self.launch_uri = launch_uri
        self.from_protocol = launch_uri is not None
        self.clicker = Clicker(cfg)
        self.thread = None
        self.worker = None
        self.watcher = None

        self.setWindowTitle(config.APP_NAME)
        self.resize(1000, 640)
        self.setMinimumSize(860, 560)

        self.root = Root(cfg)
        outer = QHBoxLayout(self.root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(200)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.setSpacing(6)
        logo = QLabel(config.APP_NAME)
        logo.setObjectName("Logo")
        sl.addWidget(logo)

        self.stack = QStackedWidget()
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        pages = [("Home", self._home()), ("Mods", self._mods()), ("Fast Flags", self._flags()),
                 ("Look", self._look()), ("Settings", self._settings())]
        for i, (name, page) in enumerate(pages):
            b = QPushButton(name)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.nav.addButton(b, i)
            sl.addWidget(b)
            self.stack.addWidget(page)
        self.nav.idClicked.connect(self.stack.setCurrentIndex)
        sl.addStretch(1)
        ver = QLabel(f"v{config.APP_VERSION}")
        ver.setObjectName("Muted")
        sl.addWidget(ver)

        outer.addWidget(side)
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(self.root)

        # tray (used while Roblox runs in the background)
        self.tray = QSystemTrayIcon(self)
        menu = QMenu()
        a_show = QAction("Show", self)
        a_show.triggered.connect(self._restore)
        a_quit = QAction("Quit", self)
        a_quit.triggered.connect(self._quit)
        menu.addAction(a_show)
        menu.addAction(a_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._restore() if r == QSystemTrayIcon.Trigger else None)

        for b in self.findChildren(QPushButton):
            b.pressed.connect(self.clicker.play)
        for c in self.findChildren(QCheckBox):
            c.clicked.connect(self.clicker.play)

        self.apply_style()
        self.refresh_home()
        if self.from_protocol:
            self.start_launch(self.launch_uri)

    # ------------------------------------------------ layout helpers
    def _page(self, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(14)
        t = QLabel(title)
        t.setObjectName("H1")
        lay.addWidget(t)
        scroll.setWidget(inner)
        return scroll, lay

    def apply_style(self):
        self.setStyleSheet(stylesheet(self.cfg))
        icon = make_icon(self.cfg["accent"])
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)
        self.root.reload()
        if hasattr(self, "accent_btn"):
            self.accent_btn.setStyleSheet(f"background:{self.cfg['accent']};")
            self.bg_btn.setStyleSheet(f"background:{self.cfg['background']};")

    def _save(self):
        self.cfg.save()

    # ------------------------------------------------ home
    def _home(self):
        page, lay = self._page("Roblox")
        self.version_lbl = QLabel()
        self.version_lbl.setObjectName("Muted")
        lay.addWidget(self.version_lbl)

        self.default_card, dl = card(None, "Chrome Blox isn't your default Roblox launcher yet, so Play on the "
                                           "Roblox website still opens the normal one.")
        b = QPushButton("Set as default")
        b.clicked.connect(self._set_default)
        dl.addWidget(row(b))
        lay.addWidget(self.default_card)

        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("Play")
        self.play_btn.clicked.connect(lambda: self.start_launch(None))
        lay.addSpacing(6)
        lay.addWidget(row(self.play_btn))

        self.join_edit = QLineEdit()
        self.join_edit.setPlaceholderText("Place ID or game link")
        self.join_edit.setMinimumWidth(320)
        self.join_edit.returnPressed.connect(self._join)
        self.join_btn = QPushButton("Join")
        self.join_btn.clicked.connect(self._join)
        lay.addWidget(row(self.join_edit, self.join_btn))

        self.status_lbl = QLabel("Ready")
        self.status_lbl.setObjectName("Muted")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        lay.addWidget(self.status_lbl)
        lay.addWidget(self.progress)

        self.now_card, nl = card()
        self.now_icon = QLabel()
        self.now_icon.setFixedSize(64, 64)
        self.now_name = QLabel()
        self.now_name.setObjectName("H2")
        self.now_sub = QLabel()
        self.now_sub.setObjectName("Muted")
        txt = QWidget()
        tl = QVBoxLayout(txt)
        tl.setContentsMargins(0, 0, 0, 0)
        small = QLabel("NOW PLAYING")
        small.setObjectName("Muted")
        tl.addWidget(small)
        tl.addWidget(self.now_name)
        tl.addWidget(self.now_sub)
        nl.addWidget(row(self.now_icon, txt))
        self.now_card.hide()
        lay.addWidget(self.now_card)
        lay.addStretch(1)
        return page

    def refresh_home(self):
        v = self.cfg.get("current_version")
        self.version_lbl.setText(v if roblox.is_installed(v) else "Not installed yet, first Play downloads it")
        self.default_card.setVisible(os.name == "nt" and not roblox.protocols_registered())
        if hasattr(self, "default_lbl"):
            self.default_lbl.setText("Chrome Blox is your default Roblox launcher." if roblox.protocols_registered()
                                     else "Not the default launcher right now.")

    def _set_default(self):
        try:
            roblox.register_protocols()
        except Exception as e:
            QMessageBox.warning(self, config.APP_NAME, scrub(e))
        self.refresh_home()

    def _join(self):
        m = re.search(r"(\d{3,})", self.join_edit.text())
        if not m:
            self.status_lbl.setText("Paste a place ID or a roblox.com/games/… link")
            return
        self.start_launch(f"roblox://experiences/start?placeId={m.group(1)}")

    # ------------------------------------------------ launching
    def _busy(self, busy):
        for w in (self.play_btn, self.join_btn, self.join_edit, self.reinstall_btn):
            w.setEnabled(not busy)

    def start_launch(self, uri, launch=True):
        if self.thread is not None:
            return
        self._busy(True)
        self.progress.setValue(0)
        self.progress.show()
        self.thread = QThread()
        self.worker = LaunchWorker(self.cfg, uri, launch)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.status.connect(self.status_lbl.setText)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.done.connect(self._launched)
        self.worker.failed.connect(self._failed)
        self.worker.done.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._thread_done)
        self.thread.start()

    def _thread_done(self):
        self.worker.deleteLater()
        self.thread.deleteLater()
        self.worker = self.thread = None
        self._busy(False)
        self.progress.hide()
        self.refresh_home()

    def _failed(self, msg):
        self.status_lbl.setText("Something went wrong")
        self._restore()
        QMessageBox.warning(self, config.APP_NAME, msg)

    def _launched(self, proc):
        if proc is None:
            self.status_lbl.setText("Roblox is installed and up to date")
            return
        self.status_lbl.setText("Roblox is running")
        if self.watcher:
            self.watcher.stop()
        self.watcher = presence.ActivityWatcher(self.cfg, proc)
        self.watcher.joined.connect(self._show_game)
        self.watcher.updated.connect(self._show_game)
        self.watcher.left.connect(self.now_card.hide)
        self.watcher.closed.connect(self._roblox_closed)
        self.watcher.start()
        if self.from_protocol:
            self.tray.show()
            self.hide()
        else:
            self.showMinimized()

    def _show_game(self, g):
        self.now_name.setText(g.get("name", "Roblox"))
        bits = [f"by {g['creator']}"] if g.get("creator") else []
        if g.get("region"):
            bits.append(f"Server: {g['region']}")
        self.now_sub.setText("  ·  ".join(bits))
        pm = QPixmap()
        if g.get("icon") and pm.loadFromData(g["icon"]):
            self.now_icon.setPixmap(pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.now_icon.clear()
        self.now_card.show()

    def _roblox_closed(self):
        self.watcher = None
        self.now_card.hide()
        self.status_lbl.setText("Ready")
        if self.isHidden():
            self._quit()

    def _restore(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self):
        if self.watcher:
            self.watcher.stop()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, e):
        if self.watcher and self.watcher.running():
            e.ignore()
            self.tray.show()
            self.hide()
            self.tray.showMessage(config.APP_NAME, "Still running while Roblox is open.", QSystemTrayIcon.NoIcon, 2500)
        else:
            e.accept()
            self._quit()

    # ------------------------------------------------ mods
    def _mods(self):
        page, lay = self._page("Mods")
        c, cl = card("Mods folder", "Anything in here gets copied over Roblox's files every launch, using the same "
                                    "folder layout. Example: put the old oof sound at content/sounds/ouch.ogg. "
                                    "Delete a file and it goes back to normal.")
        b = QPushButton("Open mods folder")
        b.clicked.connect(lambda: os.startfile(str(config.MODS)) if os.name == "nt" else None)
        cl.addWidget(row(b))
        lay.addWidget(c)

        c, cl = card("Custom font", "Swaps every in-game font for one .ttf or .otf file.")
        self.font_lbl = QLabel()
        self.font_lbl.setObjectName("Muted")
        pick = QPushButton("Choose font…")
        pick.clicked.connect(self._pick_font)
        reset = QPushButton("Reset")
        reset.clicked.connect(lambda: self._set_mod_file("custom_font", ""))
        cl.addWidget(self.font_lbl)
        cl.addWidget(row(pick, reset))
        lay.addWidget(c)

        c, cl = card("Custom cursor", "Use any PNG as your mouse cursor in game (64×64 looks best).")
        self.cursor_lbl = QLabel()
        self.cursor_lbl.setObjectName("Muted")
        pick = QPushButton("Choose PNG…")
        pick.clicked.connect(self._pick_cursor)
        reset = QPushButton("Reset")
        reset.clicked.connect(lambda: self._set_mod_file("custom_cursor", ""))
        cl.addWidget(self.cursor_lbl)
        cl.addWidget(row(pick, reset))
        lay.addWidget(c)

        note = QLabel("Mod changes apply the next time you launch Roblox.")
        note.setObjectName("Muted")
        lay.addWidget(note)
        lay.addStretch(1)
        self._refresh_mod_labels()
        return page

    def _refresh_mod_labels(self):
        f, c = self.cfg.get("custom_font"), self.cfg.get("custom_cursor")
        self.font_lbl.setText(f"Using: {Path(f).name}" if f else "Using Roblox's fonts")
        self.cursor_lbl.setText(f"Using: {Path(c).name}" if c else "Using Roblox's cursor")

    def _store_copy(self, src, name):
        dest_dir = config.BASE / "assets"
        dest_dir.mkdir(exist_ok=True)
        dest = dest_dir / (name + Path(src).suffix.lower())
        shutil.copy2(src, dest)
        return str(dest)

    def _set_mod_file(self, key, value):
        self.cfg[key] = value
        self._save()
        self._refresh_mod_labels()

    def _pick_font(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a font", "", "Fonts (*.ttf *.otf)")
        if p:
            stored = self._store_copy(p, "font")
            self._set_mod_file("custom_font", stored)
            self.font_lbl.setText(f"Using: {Path(p).name}")

    def _pick_cursor(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a cursor", "", "PNG images (*.png)")
        if p:
            stored = self._store_copy(p, "cursor")
            self._set_mod_file("custom_cursor", stored)
            self.cursor_lbl.setText(f"Using: {Path(p).name}")

    # ------------------------------------------------ fast flags
    def _flags(self):
        page, lay = self._page("Fast Flags")
        c, cl = card(None, "Roblox only accepts flags on their allowlist now, so anything else here just gets "
                           "ignored by the game. These apply next launch.")
        lay.addWidget(c)

        c, cl = card("Quick settings")
        self.preset_boxes = {}
        for group, options in FLAG_PRESETS.items():
            lbl = QLabel(group)
            lbl.setMinimumWidth(170)
            box = QComboBox()
            box.addItems(list(options))
            box.setMinimumWidth(160)
            box.setCurrentText(self._detect_preset(group))
            box.currentTextChanged.connect(lambda val, g=group: self._apply_preset(g, val))
            self.preset_boxes[group] = box
            cl.addWidget(row(lbl, box))
        lay.addWidget(c)

        c, cl = card("All flags (JSON)")
        self.flags_edit = QPlainTextEdit()
        self.flags_edit.setMinimumHeight(180)
        self.flags_edit.setPlainText(json.dumps(self.cfg.get("fflags") or {}, indent=2))
        save = QPushButton("Save")
        save.clicked.connect(self._save_flags)
        clear = QPushButton("Reset all")
        clear.clicked.connect(self._clear_flags)
        self.flags_msg = QLabel()
        self.flags_msg.setObjectName("Muted")
        cl.addWidget(self.flags_edit)
        cl.addWidget(row(save, clear, self.flags_msg))
        lay.addWidget(c)
        lay.addStretch(1)
        return page

    def _detect_preset(self, group):
        flags = self.cfg.get("fflags") or {}
        for name, vals in FLAG_PRESETS[group].items():
            if vals and all(flags.get(k) == v for k, v in vals.items()):
                return name
        return "Automatic"

    def _apply_preset(self, group, value):
        flags = dict(self.cfg.get("fflags") or {})
        for vals in FLAG_PRESETS[group].values():
            for k in vals:
                flags.pop(k, None)
        flags.update(FLAG_PRESETS[group][value])
        self.cfg["fflags"] = flags
        self._save()
        self.flags_edit.setPlainText(json.dumps(flags, indent=2))
        self.flags_msg.setText("Saved")

    def _save_flags(self):
        try:
            data = json.loads(self.flags_edit.toPlainText() or "{}")
            if not isinstance(data, dict):
                raise ValueError("needs to be a { } object")
        except Exception as e:
            self.flags_msg.setText(f"Not valid JSON: {e}")
            return
        self.cfg["fflags"] = data
        self._save()
        for g, box in self.preset_boxes.items():
            box.blockSignals(True)
            box.setCurrentText(self._detect_preset(g))
            box.blockSignals(False)
        self.flags_msg.setText("Saved")

    def _clear_flags(self):
        self.flags_edit.setPlainText("{}")
        self._save_flags()

    # ------------------------------------------------ look
    def _look(self):
        page, lay = self._page("Look")
        c, cl = card("Colors")
        self.accent_btn = QPushButton()
        self.accent_btn.setObjectName("Swatch")
        self.accent_btn.clicked.connect(lambda: self._pick_color("accent"))
        self.bg_btn = QPushButton()
        self.bg_btn.setObjectName("Swatch")
        self.bg_btn.clicked.connect(lambda: self._pick_color("background"))
        a = QLabel("Accent")
        a.setMinimumWidth(110)
        bgl = QLabel("Background")
        bgl.setMinimumWidth(110)
        cl.addWidget(row(a, self.accent_btn))
        cl.addWidget(row(bgl, self.bg_btn))
        reset = QPushButton("Reset colors")
        reset.clicked.connect(self._reset_colors)
        cl.addWidget(row(reset))
        lay.addWidget(c)

        c, cl = card("Background image")
        pick = QPushButton("Choose image…")
        pick.clicked.connect(self._pick_bg)
        clear = QPushButton("Remove")
        clear.clicked.connect(lambda: (self.cfg.__setitem__("bg_image", ""), self._save(), self.apply_style()))
        cl.addWidget(row(pick, clear))
        lay.addWidget(c)

        c, cl = card("Click sound", "Same sound for every button, play and errors included.")
        on = QCheckBox("Play click sound")
        on.setChecked(self.cfg.get("click_sound", True))
        on.toggled.connect(lambda v: (self.cfg.__setitem__("click_sound", v), self._save()))
        cl.addWidget(on)
        vol = QSlider(Qt.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(int(self.cfg.get("volume", 0.6) * 100))
        vol.setFixedWidth(220)
        vol.sliderReleased.connect(lambda: self._set_volume(vol.value()))
        vl = QLabel("Volume")
        vl.setMinimumWidth(110)
        cl.addWidget(row(vl, vol))
        own = QPushButton("Use my own .wav…")
        own.clicked.connect(self._pick_sound)
        back = QPushButton("Default sound")
        back.clicked.connect(lambda: self._use_custom_sound(False))
        cl.addWidget(row(own, back))
        lay.addWidget(c)
        lay.addStretch(1)
        return page

    def _pick_color(self, key):
        col = QColorDialog.getColor(QColor(self.cfg[key]), self, "Pick a color")
        if col.isValid():
            self.cfg[key] = col.name()
            self._save()
            self.apply_style()

    def _reset_colors(self):
        self.cfg["accent"] = config.DEFAULTS["accent"]
        self.cfg["background"] = config.DEFAULTS["background"]
        self._save()
        self.apply_style()

    def _pick_bg(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a background", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if p:
            self.cfg["bg_image"] = self._store_copy(p, "background")
            self._save()
            self.apply_style()

    def _set_volume(self, v):
        self.cfg["volume"] = v / 100
        self._save()
        self.clicker.rebuild()
        self.clicker.play()

    def _pick_sound(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a click sound", "", "WAV sound (*.wav)")
        if p:
            shutil.copy2(p, CUSTOM_SOUND)
            self._use_custom_sound(True)

    def _use_custom_sound(self, on):
        self.cfg["custom_sound"] = on
        self._save()
        self.clicker.rebuild()
        self.clicker.play()

    # ------------------------------------------------ settings
    def _settings(self):
        page, lay = self._page("Settings")
        c, cl = card("Default launcher", "When Chrome Blox is the default, Play buttons on roblox.com open it. "
                                         "If the normal Roblox installer runs again it can steal this back, just "
                                         "press the button again.")
        self.default_lbl = QLabel()
        self.default_lbl.setObjectName("Muted")
        b = QPushButton("Set Chrome Blox as default")
        b.clicked.connect(self._set_default)
        cl.addWidget(self.default_lbl)
        cl.addWidget(row(b))
        lay.addWidget(c)

        c, cl = card("Discord", "Shows the game you're playing on your Discord profile. Make an app at "
                                "discord.com/developers/applications (name it whatever you want Discord to show, "
                                "e.g. Roblox), then paste its Application ID here.")
        rpc = QCheckBox("Show what I'm playing on Discord")
        rpc.setChecked(self.cfg.get("discord_rpc", False))
        rpc.toggled.connect(lambda v: (self.cfg.__setitem__("discord_rpc", v), self._save()))
        app_id = QLineEdit(self.cfg.get("discord_app_id", ""))
        app_id.setPlaceholderText("Application ID")
        app_id.setFixedWidth(260)
        app_id.editingFinished.connect(lambda: (self.cfg.__setitem__("discord_app_id", app_id.text().strip()),
                                                self._save()))
        region = QCheckBox("Show server location")
        region.setChecked(self.cfg.get("show_region", True))
        region.toggled.connect(lambda v: (self.cfg.__setitem__("show_region", v), self._save()))
        cl.addWidget(rpc)
        cl.addWidget(app_id)
        cl.addWidget(region)
        lay.addWidget(c)

        c, cl = card("Roblox")
        multi = QCheckBox("Allow more than one Roblox window at once")
        multi.setChecked(self.cfg.get("multi_instance", False))
        multi.toggled.connect(lambda v: (self.cfg.__setitem__("multi_instance", v), self._save()))
        cl.addWidget(multi)
        self.reinstall_btn = QPushButton("Reinstall Roblox")
        self.reinstall_btn.clicked.connect(self._reinstall)
        cache = QPushButton("Clear download cache")
        cache.clicked.connect(self._clear_cache)
        cl.addWidget(row(self.reinstall_btn, cache))
        lay.addWidget(c)
        lay.addStretch(1)
        return page

    def _reinstall(self):
        v = self.cfg.get("current_version")
        if v:
            shutil.rmtree(roblox.client_dir(v), ignore_errors=True)
        self.nav.button(0).click()
        self.start_launch(None, launch=False)

    def _clear_cache(self):
        shutil.rmtree(config.DOWNLOADS, ignore_errors=True)
        config.DOWNLOADS.mkdir(parents=True, exist_ok=True)
        QMessageBox.information(self, config.APP_NAME, "Download cache cleared.")
