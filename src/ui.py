import json
import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QThread, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSlider, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

import config
import mods
import presence
import roblox
import shortcuts
import sound
import theme as th


from pages import ExtraPages
from widgets import app_icon, card, dot_icon, ghost, header, label, row, scrub


class SfxFilter(QObject):
    """Creamy click for every button and checkbox in the app."""
    def __init__(self, clicker):
        super().__init__()
        self.clicker = clicker

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonPress and isinstance(obj, (QPushButton, QCheckBox)) \
                and obj.isEnabled():
            self.clicker.play()
        return False


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

    def has_image(self):
        return bool(self._pix and not self._pix.isNull())

    def paintEvent(self, e):
        p = QPainter(self)
        bg = QColor(th.clean_theme(self.cfg.get("theme"))["bg"])
        p.fillRect(self.rect(), bg)
        if self.has_image():
            s = self._pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, s, (s.width() - self.width()) // 2, (s.height() - self.height()) // 2,
                         self.width(), self.height())
            bg.setAlpha(120)
            p.fillRect(self.rect(), bg)


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
            self.status.emit("Checking for Roblox updates...")
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
            self.status.emit("Applying mods...")
            mods.apply_mods(folder, self.cfg)
            self.status.emit("Starting Roblox...")
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
    "Anti-aliasing": {
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

NAV = ("Play", "Servers", "Avatar", "Mods", "Fast Flags", "Appearance", "Settings")


# ---------------------------------------------------------------- main window
class MainWindow(QMainWindow, ExtraPages):
    def __init__(self, cfg, launch_uri=None):
        super().__init__()
        self.cfg = cfg
        self.cfg["theme"] = th.clean_theme(cfg.get("theme"))
        self.launch_uri = launch_uri
        self.from_protocol = launch_uri is not None
        self.clicker = sound.Clicker(cfg)
        self.thread = self.worker = self.watcher = None
        self.swatches, self.hex_edits = {}, {}
        self._init_extra()

        self.setWindowTitle(config.APP_NAME)
        self.resize(1000, 660)
        self.setMinimumSize(880, 580)

        self.root = Root(cfg)
        self.setCentralWidget(self.root)
        outer = QHBoxLayout(self.root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())
        self.stack = QStackedWidget()
        for build in (self._play, self._servers, self._avatar, self._mods, self._flags, self._appearance,
                      self._settings):
            self.stack.addWidget(build())
        outer.addWidget(self.stack, 1)

        # tray (used while Roblox runs in the background)
        self.tray = QSystemTrayIcon(self)
        menu = QMenu()
        for text, fn in (("Show", self._restore), ("Quit", self._quit)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self._restore() if r == QSystemTrayIcon.ActivationReason.Trigger else None)

        self._sfx = SfxFilter(self.clicker)
        QApplication.instance().installEventFilter(self._sfx)

        self.apply_theme(self.cfg["theme"], save=False)
        self.nav_buttons[0].setChecked(True)
        self.refresh_play()
        self._restore_session()
        self._scan_recent_from_logs()
        if self.from_protocol:
            self.start_launch(self.launch_uri)

    # ------------------------------------------------ shell
    def _sidebar(self):
        sb = QWidget()
        sb.setObjectName("sidebar")
        sb.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sb.setFixedWidth(220)
        lay = QVBoxLayout(sb)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(4)
        lay.addWidget(label(config.APP_NAME, "brand"))
        lay.addWidget(label("Roblox launcher", "muted"))
        lay.addSpacing(14)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for i, name in enumerate(NAV):
            b = QPushButton(name)
            b.setProperty("nav", True)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.stack.setCurrentIndex(i))
            self.nav_group.addButton(b)
            self.nav_buttons.append(b)
            lay.addWidget(b)
        lay.addStretch(1)

        chip = QFrame()
        chip.setProperty("chip", True)
        cl = QHBoxLayout(chip)
        cl.setContentsMargins(10, 10, 10, 10)
        self.avatar_chip = QLabel("R")
        self.avatar_chip.setObjectName("avatar")
        self.avatar_chip.setFixedSize(36, 36)
        self.avatar_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.avatar_chip)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.acc_name = label("Not signed in", "h2")
        col.addWidget(self.acc_name)
        self.acc_btn = ghost(QPushButton("Sign in"))
        self.acc_btn.clicked.connect(self._account_clicked)
        col.addWidget(self.acc_btn)
        cl.addLayout(col, 1)
        lay.addWidget(chip)
        return sb

    def _page(self, title, sub):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(16)
        lay.addLayout(header(title, sub))
        scroll.setWidget(inner)
        return scroll, lay

    def apply_theme(self, theme, save=True):
        theme = th.clean_theme(theme)
        self.cfg["theme"] = theme
        self.root.reload()
        QApplication.instance().setStyleSheet(th.build_qss(theme, self.root.has_image()))
        icon = app_icon(theme["accent"])
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)
        for k, sw in self.swatches.items():
            sw.setStyleSheet(f"background: {theme[k]}; border: 2px solid "
                             f"{th.mix(theme['surface'], theme['text'], 0.35)}; border-radius: 8px;")
            self.hex_edits[k].setText(theme[k])
        if save:
            self.cfg.save()

    # ------------------------------------------------ play
    def _play(self):
        page, lay = self._page("Play", "Jump into Roblox, or join any game by its link.")

        self.default_card, dl = card()
        dl.addWidget(label("Not your default launcher yet", "h2"))
        dl.addWidget(label("Play buttons on roblox.com still open the normal Roblox. "
                           "Make them open Chrome Blox instead.", "muted"))
        b = QPushButton("Set as default")
        b.clicked.connect(self._set_default)
        dl.addWidget(row(b))
        lay.addWidget(self.default_card)

        c, cl = card()
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(14)
        g.setColumnStretch(1, 1)
        g.addWidget(label("Join game", "h2"), 0, 0)
        self.join_edit = QLineEdit()
        self.join_edit.setPlaceholderText("Paste a game link or place ID")
        self.join_edit.returnPressed.connect(self._join)
        g.addWidget(self.join_edit, 0, 1)
        self.join_btn = QPushButton("Join")
        self.join_btn.clicked.connect(self._join)
        g.addWidget(self.join_btn, 0, 2)
        g.addWidget(label("Version", "h2"), 1, 0)
        self.version_lbl = label("", "muted")
        g.addWidget(self.version_lbl, 1, 1, 1, 2)
        cl.addLayout(g)
        lay.addWidget(c)

        self.play_btn = QPushButton("Play")
        self.play_btn.setProperty("primary", True)
        self.play_btn.setMinimumHeight(52)
        self.play_btn.clicked.connect(lambda: self.start_launch(None))
        lay.addWidget(self.play_btn)
        self.status_lbl = label("Ready", "muted")
        lay.addWidget(self.status_lbl)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        lay.addWidget(self.progress)

        lay.addWidget(self._recent_section("Jump back in", self._join_place))

        self.now_card, nl = card((16, 14, 16, 14))
        self.now_icon = QLabel()
        self.now_icon.setObjectName("gameicon")
        self.now_icon.setFixedSize(64, 64)
        txt = QWidget()
        tl = QVBoxLayout(txt)
        tl.setContentsMargins(4, 0, 0, 0)
        tl.setSpacing(2)
        tl.addWidget(label("NOW PLAYING", "small"))
        self.now_name = label("", "h2")
        self.now_sub = label("", "muted")
        self.now_sub.setWordWrap(False)
        tl.addWidget(self.now_name)
        tl.addWidget(self.now_sub)
        nl.addWidget(row(self.now_icon, txt))
        self.now_card.hide()
        lay.addWidget(self.now_card)
        lay.addStretch(1)
        return page

    def refresh_play(self):
        v = self.cfg.get("current_version")
        installed = roblox.is_installed(v)
        self.version_lbl.setText(v if installed else "Not installed yet, first Play downloads it")
        is_default = roblox.protocols_registered()
        self.default_card.setVisible(os.name == "nt" and not is_default)
        self.default_lbl.setText("Chrome Blox is your default Roblox launcher." if is_default
                                 else "Not the default launcher right now.")

    def _set_default(self):
        try:
            roblox.register_protocols()
        except Exception as e:
            QMessageBox.warning(self, config.APP_NAME, scrub(e))
        self.refresh_play()

    def _join_place(self, place_id):
        self.start_launch(f"roblox://experiences/start?placeId={place_id}")

    def _join(self):
        m = re.search(r"(\d{3,})", self.join_edit.text())
        if not m:
            self.status_lbl.setText("Paste a place ID or a roblox.com/games/... link")
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
        self.refresh_play()

    def _failed(self, msg):
        self.status_lbl.setText("Something went wrong")
        self.progress.setValue(0)
        self._restore()
        QMessageBox.warning(self, config.APP_NAME, msg)

    def _launched(self, proc):
        self.progress.setValue(100)
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
            self.now_icon.setPixmap(pm.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        else:
            self.now_icon.clear()
        self.now_card.show()
        self._remember_game(g)

    def _roblox_closed(self):
        self.watcher = None
        self.now_card.hide()
        self.status_lbl.setText("Ready")
        self.progress.setValue(0)
        self.refresh_play()
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
            self.tray.showMessage(config.APP_NAME, "Still running while Roblox is open.",
                                  QSystemTrayIcon.MessageIcon.NoIcon, 2500)
        else:
            e.accept()
            self._quit()

    # ------------------------------------------------ mods
    def _mods(self):
        page, lay = self._page("Mods", "Change how Roblox looks and sounds on your PC only. Applies next launch.")

        c, cl = card()
        cl.addWidget(label("Custom font", "h2"))
        cl.addWidget(label("Swap every in-game font for one .ttf or .otf file.", "muted"))
        self.font_lbl = label("", "muted")
        pick = QPushButton("Choose font...")
        pick.clicked.connect(self._pick_font)
        reset = ghost(QPushButton("Reset"))
        reset.clicked.connect(lambda: self._set_mod_file("custom_font", ""))
        cl.addWidget(self.font_lbl)
        cl.addWidget(row(pick, reset))
        lay.addWidget(c)

        c, cl = card()
        cl.addWidget(label("Custom cursor", "h2"))
        cl.addWidget(label("Use any PNG as your mouse cursor in game (64×64 looks best).", "muted"))
        self.cursor_lbl = label("", "muted")
        pick = QPushButton("Choose PNG...")
        pick.clicked.connect(self._pick_cursor)
        reset = ghost(QPushButton("Reset"))
        reset.clicked.connect(lambda: self._set_mod_file("custom_cursor", ""))
        cl.addWidget(self.cursor_lbl)
        cl.addWidget(row(pick, reset))
        lay.addWidget(c)

        c, cl = card()
        cl.addWidget(label("Mods folder", "h2"))
        cl.addWidget(label("Files in here replace Roblox's own files every launch (same folder layout). "
                           "Example: an old oof sound at content/sounds/ouch.ogg. Delete a file to undo it.",
                           "muted"))
        b = QPushButton("Open mods folder")
        b.clicked.connect(lambda: os.startfile(str(config.MODS)) if os.name == "nt" else None)
        cl.addWidget(row(b))
        lay.addWidget(c)
        lay.addStretch(1)
        self._refresh_mod_labels()
        return page

    def _refresh_mod_labels(self):
        f, c = self.cfg.get("custom_font"), self.cfg.get("custom_cursor")
        self.font_lbl.setText("Using your font" if f else "Using Roblox's fonts")
        self.cursor_lbl.setText("Using your cursor" if c else "Using Roblox's cursor")

    def _store_copy(self, src, name):
        d = config.BASE / "assets"
        d.mkdir(exist_ok=True)
        dest = d / (name + Path(src).suffix.lower())
        shutil.copy2(src, dest)
        return str(dest)

    def _set_mod_file(self, key, value):
        self.cfg[key] = value
        self.cfg.save()
        self._refresh_mod_labels()

    def _pick_font(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a font", "", "Fonts (*.ttf *.otf)")
        if p:
            self._set_mod_file("custom_font", self._store_copy(p, "font"))

    def _pick_cursor(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a cursor", "", "PNG images (*.png)")
        if p:
            self._set_mod_file("custom_cursor", self._store_copy(p, "cursor"))

    # ------------------------------------------------ fast flags
    def _flags(self):
        page, lay = self._page("Fast Flags", "Engine tweaks. Roblox ignores any flag that isn't on its allowlist.")

        c, cl = card()
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(12)
        g.setColumnStretch(2, 1)
        self.preset_boxes = {}
        for i, (group, options) in enumerate(FLAG_PRESETS.items()):
            g.addWidget(label(group, "h2"), i, 0)
            box = QComboBox()
            box.addItems(list(options))
            box.setMinimumWidth(180)
            box.setCurrentText(self._detect_preset(group))
            box.currentTextChanged.connect(lambda val, gr=group: self._apply_preset(gr, val))
            self.preset_boxes[group] = box
            g.addWidget(box, i, 1)
        cl.addLayout(g)
        lay.addWidget(c)

        c, cl = card()
        cl.addWidget(label("All flags (JSON)", "h2"))
        self.flags_edit = QPlainTextEdit()
        self.flags_edit.setMinimumHeight(170)
        self.flags_edit.setPlainText(json.dumps(self.cfg.get("fflags") or {}, indent=2))
        save = QPushButton("Save")
        save.clicked.connect(self._save_flags)
        clear = ghost(QPushButton("Reset all"))
        clear.clicked.connect(self._clear_flags)
        self.flags_msg = label("", "muted")
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
        self.cfg.save()
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
        self.cfg.save()
        for g, box in self.preset_boxes.items():
            box.blockSignals(True)
            box.setCurrentText(self._detect_preset(g))
            box.blockSignals(False)
        self.flags_msg.setText("Saved")

    def _clear_flags(self):
        self.flags_edit.setPlainText("{}")
        self._save_flags()

    # ------------------------------------------------ appearance
    def _appearance(self):
        page, lay = self._page("Appearance", "Recolor the whole launcher. Changes apply instantly and are saved.")

        c, cl = card()
        cl.addWidget(label("Presets", "h2"))
        pg = QGridLayout()
        pg.setSpacing(8)
        for i, (name, t) in enumerate(th.PRESETS.items()):
            b = QPushButton(name)
            b.setIcon(dot_icon(t["accent"]))
            b.clicked.connect(lambda _=False, t=t: self.apply_theme(dict(t)))
            pg.addWidget(b, i // 4, i % 4)
        cl.addLayout(pg)
        lay.addWidget(c)

        c, cl = card()
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(12)
        g.addWidget(label("Custom colors", "h2"), 0, 0, 1, 4)
        for i, (key, title) in enumerate((("bg", "Background"), ("surface", "Cards & sidebar"),
                                          ("accent", "Accent"), ("text", "Text")), start=1):
            g.addWidget(QLabel(title), i, 0)
            sw = QPushButton()
            sw.setFixedSize(54, 32)
            sw.clicked.connect(lambda _=False, k=key: self._pick_color(k))
            g.addWidget(sw, i, 1)
            he = QLineEdit()
            he.setMaximumWidth(110)
            he.editingFinished.connect(lambda k=key: self._hex_edited(k))
            g.addWidget(he, i, 2)
            self.swatches[key], self.hex_edits[key] = sw, he
        g.setColumnStretch(3, 1)
        reset = ghost(QPushButton("Reset to default"))
        reset.clicked.connect(lambda: self.apply_theme(dict(th.DEFAULT_THEME)))
        g.addWidget(reset, 5, 0, 1, 2)
        cl.addLayout(g)
        lay.addWidget(c)

        c, cl = card()
        cl.addWidget(label("Background image", "h2"))
        cl.addWidget(label("Shows behind everything, cards go see-through.", "muted"))
        pick = QPushButton("Choose image...")
        pick.clicked.connect(self._pick_bg)
        clear = ghost(QPushButton("Remove"))
        clear.clicked.connect(self._clear_bg)
        cl.addWidget(row(pick, clear))
        lay.addWidget(c)

        c, cl = card()
        cl.addWidget(label("Click sound", "h2"))
        on = QCheckBox("Play the click sound")
        on.setChecked(self.cfg.get("click_sound", True))
        on.toggled.connect(lambda v: (self.cfg.__setitem__("click_sound", v), self.cfg.save()))
        cl.addWidget(on)
        vol = QSlider(Qt.Orientation.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(int(self.cfg.get("volume", 0.6) * 100))
        vol.setFixedWidth(240)
        vol.sliderReleased.connect(lambda: self._set_volume(vol.value()))
        vl = QLabel("Volume")
        vl.setMinimumWidth(80)
        cl.addWidget(row(vl, vol))
        own = QPushButton("Use my own sound...")
        own.clicked.connect(self._pick_sound)
        back = ghost(QPushButton("Creamy default"))
        back.clicked.connect(lambda: self._use_custom_sound(False))
        cl.addWidget(row(own, back))
        lay.addWidget(c)
        lay.addStretch(1)
        return page

    def _pick_color(self, key):
        col = QColorDialog.getColor(QColor(self.cfg["theme"][key]), self, f"Pick {key} color")
        if col.isValid():
            self.apply_theme({**self.cfg["theme"], key: col.name()})

    def _hex_edited(self, key):
        txt = self.hex_edits[key].text().strip()
        if not txt.startswith("#"):
            txt = "#" + txt
        if QColor(txt).isValid():
            self.apply_theme({**self.cfg["theme"], key: QColor(txt).name()})
        else:
            self.hex_edits[key].setText(self.cfg["theme"][key])

    def _pick_bg(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a background", "",
                                           "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if p:
            self.cfg["bg_image"] = self._store_copy(p, "background")
            self.apply_theme(self.cfg["theme"])

    def _clear_bg(self):
        self.cfg["bg_image"] = ""
        self.apply_theme(self.cfg["theme"])

    def _set_volume(self, v):
        self.cfg["volume"] = v / 100
        self.cfg.save()
        self.clicker.rebuild()
        self.clicker.play()

    def _pick_sound(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a click sound", "", "Sounds (*.wav *.mp3 *.ogg *.flac)")
        if not p:
            return
        try:
            sound.import_sound(p)
        except RuntimeError as e:
            QMessageBox.warning(self, config.APP_NAME, scrub(e))
            return
        self._use_custom_sound(True)

    def _use_custom_sound(self, on):
        self.cfg["custom_sound"] = on
        self.cfg.save()
        self.clicker.rebuild()
        self.clicker.play()

    # ------------------------------------------------ settings
    def _settings(self):
        page, lay = self._page("Settings", "Launcher, Discord and Roblox options.")

        c, cl = card()
        cl.addWidget(label("Default launcher", "h2"))
        cl.addWidget(label("When Chrome Blox is the default, Play buttons on roblox.com open it. If the normal "
                           "Roblox installer runs again it can take this back, just press the button again.",
                           "muted"))
        self.default_lbl = label("", "muted")
        b = QPushButton("Set Chrome Blox as default")
        b.clicked.connect(self._set_default)
        cl.addWidget(self.default_lbl)
        cl.addWidget(row(b))
        lay.addWidget(c)

        c, cl = card()
        cl.addWidget(label("Shortcuts", "h2"))
        cl.addWidget(label("Chrome Blox makes these on first run. Deleted them? Make them again here.", "muted"))
        sc = QPushButton("Make Desktop + Start Menu shortcuts")
        sc.clicked.connect(self._make_shortcuts)
        cl.addWidget(row(sc))
        lay.addWidget(c)

        c, cl = card()
        cl.addWidget(label("Discord", "h2"))
        cl.addWidget(label("Shows the game you're in on your Discord profile. Make an app at "
                           "discord.com/developers/applications (its name is what Discord shows, e.g. Roblox), "
                           "then paste its Application ID here.", "muted"))
        rpc = QCheckBox("Show what I'm playing on Discord")
        rpc.setChecked(self.cfg.get("discord_rpc", False))
        rpc.toggled.connect(lambda v: (self.cfg.__setitem__("discord_rpc", v), self.cfg.save()))
        app_id = QLineEdit(self.cfg.get("discord_app_id", ""))
        app_id.setPlaceholderText("Application ID")
        app_id.setFixedWidth(280)
        app_id.editingFinished.connect(lambda: (self.cfg.__setitem__("discord_app_id", app_id.text().strip()),
                                                self.cfg.save()))
        region = QCheckBox("Show server location")
        region.setChecked(self.cfg.get("show_region", True))
        region.toggled.connect(lambda v: (self.cfg.__setitem__("show_region", v), self.cfg.save()))
        cl.addWidget(rpc)
        cl.addWidget(app_id)
        cl.addWidget(region)
        lay.addWidget(c)

        c, cl = card()
        cl.addWidget(label("Roblox", "h2"))
        multi = QCheckBox("Allow more than one Roblox window at once")
        multi.setChecked(self.cfg.get("multi_instance", False))
        multi.toggled.connect(lambda v: (self.cfg.__setitem__("multi_instance", v), self.cfg.save()))
        cl.addWidget(multi)
        self.reinstall_btn = QPushButton("Reinstall Roblox")
        self.reinstall_btn.clicked.connect(self._reinstall)
        cache = ghost(QPushButton("Clear download cache"))
        cache.clicked.connect(self._clear_cache)
        cl.addWidget(row(self.reinstall_btn, cache))
        lay.addWidget(c)
        lay.addStretch(1)
        return page

    def _make_shortcuts(self):
        try:
            shortcuts.create()
            QMessageBox.information(self, config.APP_NAME, "Shortcuts made on your Desktop and Start Menu.")
        except Exception as e:
            QMessageBox.warning(self, config.APP_NAME, scrub(e))

    def _reinstall(self):
        v = self.cfg.get("current_version")
        if v:
            shutil.rmtree(roblox.client_dir(v), ignore_errors=True)
        self.nav_buttons[0].click()
        self.start_launch(None, launch=False)

    def _clear_cache(self):
        shutil.rmtree(config.DOWNLOADS, ignore_errors=True)
        config.DOWNLOADS.mkdir(parents=True, exist_ok=True)
        QMessageBox.information(self, config.APP_NAME, "Download cache cleared.")
