"""Servers, Avatar and Recently played: mixed into MainWindow."""
import re
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

import account
import config
import presence
from rbxapi import api
from widgets import (
    FlowLayout, bg, card, clear_layout, ghost, label, pixmap_from, rounded, row, scrub, stack_faces,
)
import theme as th

PLACE_RE = re.compile(r"(\d{3,})")


def ping_color(ms):
    if ms is None:
        return "#8a8f98"
    if ms < 80:
        return "#1bd96a"
    if ms < 150:
        return "#f5c542"
    return "#ff4d4d"


class Clickable(QFrame):
    def __init__(self, prop, on_click, parent=None):
        super().__init__(parent)
        self.setProperty(prop, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.on_click = on_click

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.on_click:
            self.window().clicker.play()
            self.on_click()


def elide(text, px, widget):
    return QFontMetrics(widget.font()).elidedText(text, Qt.TextElideMode.ElideRight, px)


class ExtraPages:
    # ================================================================ shared state
    def _init_extra(self):
        self.me = None
        self.pix_cache = {}           # url -> QPixmap
        self.srv_place = None
        self.srv_game = None
        self.srv_cursor = None
        self.srv_data = []
        self.srv_cards = {}
        self.srv_faces = {}           # token -> url
        self.outfit_tiles = {}
        self.wearing = False
        self.cfg.setdefault("recent", [])

    def _theme_colors(self):
        t = th.clean_theme(self.cfg.get("theme"))
        return t["surface"], th.mix(t["surface"], t["text"], 0.18)

    # ================================================================ recently played
    def _recent_section(self, title, on_pick):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(label(title, "h2"))
        grid_w = QWidget()
        grid = FlowLayout(grid_w)
        lay.addWidget(grid_w)
        box._grid, box._pick = grid, on_pick
        if not hasattr(self, "_recent_boxes"):
            self._recent_boxes = []
        self._recent_boxes.append(box)
        return box

    def _render_recent(self):
        recent = self.cfg.get("recent", [])[:6]
        for box in getattr(self, "_recent_boxes", []):
            clear_layout(box._grid)
            box.setVisible(bool(recent))
            for g in recent:
                tile = Clickable("tile", lambda pid=g["place_id"], pick=box._pick: pick(pid))
                tile.setFixedSize(118, 146)
                tl = QVBoxLayout(tile)
                tl.setContentsMargins(9, 9, 9, 8)
                tl.setSpacing(6)
                ic = QLabel()
                ic.setFixedSize(100, 100)
                ic.setObjectName("gamebig")
                pm = self.pix_cache.get(g.get("icon_url", ""))
                if pm:
                    ic.setPixmap(rounded(pm, 100, radius=10))
                tl.addWidget(ic)
                nm = QLabel()
                nm.setText(elide(g.get("name") or "Game", 98, nm))
                nm.setToolTip(g.get("name") or "")
                nm.setStyleSheet("font-weight:600; font-size:12px;")
                tl.addWidget(nm)
                box._grid.addWidget(tile)

    def _remember_game(self, g):
        pid = str(g.get("place_id", ""))
        if not pid:
            return
        recent = [r for r in self.cfg.get("recent", []) if r.get("place_id") != pid]
        recent.insert(0, {"place_id": pid, "name": g.get("name", ""), "icon_url": g.get("icon_url", "")})
        self.cfg["recent"] = recent[:12]
        self.cfg.save()
        self._load_recent_icons()

    def _scan_recent_from_logs(self):
        """First run: pull recently played games out of Roblox's own logs."""
        if self.cfg.get("recent"):
            self._load_recent_icons()
            return

        def work():
            seen = []
            try:
                logs = sorted(presence.LOG_DIR.glob("*Player*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            except OSError:
                logs = []
            for log in logs[:40]:
                try:
                    text = log.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for m in presence.JOIN_RE.finditer(text):
                    if m.group(2) not in seen:
                        seen.append(m.group(2))
                if len(seen) >= 6:
                    break
            out = []
            for pid in seen[:6]:
                try:
                    g = api.game(pid)
                    out.append({"place_id": pid, "name": g["name"], "icon_url": g["icon_url"]})
                except Exception:
                    pass
            return out

        def done(out, err):
            if out:
                self.cfg["recent"] = out
                self.cfg.save()
                self._load_recent_icons()

        bg(work, done)

    def _load_recent_icons(self):
        urls = [g.get("icon_url") for g in self.cfg.get("recent", []) if g.get("icon_url")]
        missing = [u for u in urls if u not in self.pix_cache]
        if not missing:
            self._render_recent()
            return

        def done(res, err):
            for u, b in (res or {}).items():
                self.pix_cache[u] = pixmap_from(b)
            self._render_recent()

        bg(lambda: api.download_many(missing), done)

    # ================================================================ servers page
    def _servers(self):
        page, lay = self._page("Servers", "Browse every public server of a game and join the exact one you want.")

        c, cl = card()
        top = QHBoxLayout()
        top.setSpacing(8)
        self.srv_edit = QLineEdit()
        self.srv_edit.setPlaceholderText("Paste a game link or place ID")
        self.srv_edit.returnPressed.connect(self._srv_from_edit)
        go = QPushButton("Find servers")
        go.clicked.connect(self._srv_from_edit)
        top.addWidget(self.srv_edit, 1)
        top.addWidget(go)
        cl.addLayout(top)
        cl.addWidget(self._recent_section("Recently played", self._srv_open))
        lay.addWidget(c)

        # game banner
        self.game_card, gl = card((18, 16, 18, 16))
        bl = QHBoxLayout()
        bl.setSpacing(16)
        self.game_icon = QLabel()
        self.game_icon.setObjectName("gamebig")
        self.game_icon.setFixedSize(84, 84)
        bl.addWidget(self.game_icon)
        info = QVBoxLayout()
        info.setSpacing(4)
        self.game_name = label("", "h1")
        self.game_name.setStyleSheet("font-size: 21px;")
        self.game_by = label("", "muted")
        stats = QHBoxLayout()
        stats.setSpacing(6)
        self.game_playing = label("", "pill")
        self.game_servers = label("", "stat")
        stats.addWidget(self.game_playing)
        stats.addWidget(self.game_servers)
        stats.addStretch(1)
        info.addWidget(self.game_name)
        info.addWidget(self.game_by)
        info.addLayout(stats)
        bl.addLayout(info, 1)
        gl.addLayout(bl)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.srv_sort = QComboBox()
        self.srv_sort.addItems(["Most players", "Fewest players", "Best ping"])
        self.srv_sort.setMinimumWidth(160)
        self.srv_sort.currentTextChanged.connect(self._srv_sort_changed)
        self.srv_hide_full = QCheckBox("Hide full servers")
        self.srv_hide_full.toggled.connect(lambda _: self._srv_render())
        refresh = ghost(QPushButton("Refresh"))
        refresh.clicked.connect(lambda: self._srv_open(self.srv_place))
        ctrl.addWidget(label("Sort", "h2"))
        ctrl.addWidget(self.srv_sort)
        ctrl.addSpacing(8)
        ctrl.addWidget(self.srv_hide_full)
        ctrl.addStretch(1)
        ctrl.addWidget(refresh)
        gl.addLayout(ctrl)
        self.game_card.hide()
        lay.addWidget(self.game_card)

        self.srv_status = label("Paste a game, or pick one you played recently.", "muted")
        lay.addWidget(self.srv_status)

        list_w = QWidget()
        self.srv_list = QVBoxLayout(list_w)
        self.srv_list.setContentsMargins(0, 0, 0, 0)
        self.srv_list.setSpacing(10)
        lay.addWidget(list_w)

        self.srv_more = ghost(QPushButton("Load more servers"))
        self.srv_more.clicked.connect(self._srv_more_clicked)
        self.srv_more.hide()
        lay.addWidget(row(1, self.srv_more, 1, stretch=False))
        lay.addStretch(1)
        return page

    def _srv_from_edit(self):
        m = PLACE_RE.search(self.srv_edit.text())
        if not m:
            self.srv_status.setText("That doesn't look like a game link or place ID.")
            return
        self._srv_open(m.group(1))

    def _srv_order(self):
        return "Asc" if self.srv_sort.currentText() == "Fewest players" else "Desc"

    def _srv_sort_changed(self, _):
        if self.srv_place:
            self._srv_open(self.srv_place)

    def _srv_open(self, place_id):
        if not place_id:
            return
        place_id = str(place_id)
        self.nav_buttons[1].click()
        self.srv_place = place_id
        self.srv_status.setText("Loading servers...")
        self.srv_status.show()
        self.srv_more.hide()
        order = self._srv_order()

        def work():
            g = api.game(place_id)
            data, cursor = api.servers(place_id, order)
            return g, data, cursor

        def done(res, err):
            if err:
                self.srv_status.setText(scrub(err))
                self.srv_status.show()
                return
            g, data, cursor = res
            if self.srv_place != place_id:
                return
            self.srv_game, self.srv_data, self.srv_cursor = g, data, cursor
            self._srv_banner()
            self._srv_render()
            self._remember_game(g)
            self._srv_fetch_images(data, g.get("icon_url"))

        bg(work, done)

    def _srv_more_clicked(self):
        place_id, cursor, order = self.srv_place, self.srv_cursor, self._srv_order()
        if not cursor:
            return
        self.srv_more.setEnabled(False)

        def done(res, err):
            self.srv_more.setEnabled(True)
            if err:
                self.srv_status.setText(scrub(err))
                self.srv_status.show()
                return
            data, nxt = res
            if self.srv_place != place_id:
                return
            self.srv_data += data
            self.srv_cursor = nxt
            self._srv_render()
            self._srv_fetch_images(data)

        bg(lambda: api.servers(place_id, order, cursor), done)

    def _srv_banner(self):
        g = self.srv_game
        self.game_name.setText(g["name"])
        self.game_by.setText(f"by {g['creator']}" if g.get("creator") else "")
        self.game_playing.setText(f"{g.get('playing', 0):,} playing")
        pm = self.pix_cache.get(g.get("icon_url", ""))
        self.game_icon.setPixmap(rounded(pm, 84, radius=14) if pm else rounded(None, 84))
        self.game_card.show()

    def _srv_render(self):
        clear_layout(self.srv_list)
        self.srv_cards = {}
        servers = list(self.srv_data)
        if self.srv_hide_full.isChecked():
            servers = [s for s in servers if s.get("playing", 0) < s.get("maxPlayers", 1)]
        if self.srv_sort.currentText() == "Best ping":
            servers.sort(key=lambda s: s.get("ping") if s.get("ping") is not None else 9999)
        self.game_servers.setText(f"{len(self.srv_data)} servers loaded")
        self.srv_status.setText("" if servers else "No servers right now. Everyone might be in private servers.")
        self.srv_status.setVisible(not servers)
        for s in servers:
            self.srv_list.addWidget(self._server_card(s))
        self.srv_more.setVisible(bool(self.srv_cursor))

    def _server_card(self, s):
        ring, back = self._theme_colors()
        f = QFrame()
        f.setProperty("server", True)
        f.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        lay = QHBoxLayout(f)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(16)

        playing, mx = s.get("playing", 0), max(1, s.get("maxPlayers", 1))
        faces = QLabel()
        faces.setFixedWidth(150)
        tokens = s.get("playerTokens") or []
        pms = [self.pix_cache.get(self.srv_faces.get(t, "")) for t in tokens[:5]]
        faces.setPixmap(stack_faces(pms, ring=ring, backdrop=back, total=playing))
        lay.addWidget(faces)

        mid = QVBoxLayout()
        mid.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        cnt = label(f"{playing} / {mx} players", "h2")
        top.addWidget(cnt)
        if playing >= mx:
            top.addWidget(label("FULL", "stat"))
        top.addStretch(1)
        mid.addLayout(top)
        bar = QProgressBar()
        bar.setProperty("thin", True)
        bar.setTextVisible(False)
        bar.setRange(0, mx)
        bar.setValue(min(playing, mx))
        bar.setFixedWidth(220)
        mid.addWidget(bar)
        lay.addLayout(mid, 1)

        ping = s.get("ping")
        fps = s.get("fps")
        stat_box = QHBoxLayout()
        stat_box.setSpacing(6)
        p = QLabel(f"●  {ping} ms" if ping is not None else "●  ? ms")
        p.setProperty("stat", True)
        p.setStyleSheet(f"color: {ping_color(ping)};")
        stat_box.addWidget(p)
        if fps:
            stat_box.addWidget(label(f"{round(fps)} fps", "stat"))
        lay.addLayout(stat_box)

        join = QPushButton("Join")
        join.setProperty("join", True)
        join.setEnabled(playing < mx)
        sid = s.get("id")
        join.clicked.connect(lambda _=False, sid=sid: self._join_server(sid))
        lay.addWidget(join)

        f._faces, f._tokens, f._playing = faces, tokens, playing
        self.srv_cards[sid] = f
        return f

    def _join_server(self, server_id):
        if not (self.srv_place and server_id):
            return
        self.nav_buttons[0].click()
        self.start_launch(f"roblox://experiences/start?placeId={self.srv_place}&gameInstanceId={server_id}")

    def _srv_fetch_images(self, servers, icon_url=None):
        tokens = [t for s in servers for t in (s.get("playerTokens") or [])[:5]]
        place_id = self.srv_place

        def work():
            faces = api.headshots_by_token(tokens) if tokens else {}
            urls = list(faces.values()) + ([icon_url] if icon_url else [])
            return faces, api.download_many([u for u in urls if u not in self.pix_cache])

        def done(res, err):
            if err or not res or self.srv_place != place_id:
                return
            faces, imgs = res
            self.srv_faces.update(faces)
            for u, b in imgs.items():
                self.pix_cache[u] = pixmap_from(b)
            if icon_url:
                self._srv_banner()
            ring, back = self._theme_colors()
            for f in self.srv_cards.values():
                pms = [self.pix_cache.get(self.srv_faces.get(t, "")) for t in f._tokens[:5]]
                f._faces.setPixmap(stack_faces(pms, ring=ring, backdrop=back, total=f._playing))

        bg(work, done)

    # ================================================================ avatar page
    def _avatar(self):
        page, lay = self._page("Avatar", "Switch between your saved outfits in one click.")

        self.av_out, ol = card((28, 28, 28, 28))
        ol.addWidget(label("Sign in to Roblox", "h2"))
        ol.addWidget(label("Sign in once and your outfits show up here. You log in on Roblox's own page; your "
                           "session stays encrypted on this PC only.", "muted"))
        b = QPushButton("Sign in")
        b.setProperty("join", True)
        b.clicked.connect(self._sign_in)
        ol.addWidget(row(b))
        lay.addWidget(self.av_out)

        self.av_in = QWidget()
        al = QHBoxLayout(self.av_in)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(16)

        left, ll = card((18, 18, 18, 18))
        left.setFixedWidth(262)
        self.av_render = QLabel()
        self.av_render.setObjectName("render")
        self.av_render.setFixedSize(226, 260)
        self.av_render.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(self.av_render)
        self.av_display = label("", "h2")
        self.av_display.setStyleSheet("font-size: 18px;")
        self.av_user = label("", "muted")
        ll.addWidget(self.av_display)
        ll.addWidget(self.av_user)
        seg = QHBoxLayout()
        seg.setSpacing(6)
        self.av_type_group = QButtonGroup(self)
        self.av_type_btns = {}
        for t in ("R6", "R15"):
            bt = QPushButton(t)
            bt.setProperty("seg", True)
            bt.setCheckable(True)
            bt.clicked.connect(lambda _=False, t=t: self._set_type(t))
            self.av_type_group.addButton(bt)
            self.av_type_btns[t] = bt
            seg.addWidget(bt)
        seg.addStretch(1)
        ll.addLayout(seg)
        ll.addStretch(1)
        rf = ghost(QPushButton("Refresh"))
        rf.clicked.connect(self._avatar_refresh)
        so = ghost(QPushButton("Sign out"))
        so.clicked.connect(self._sign_out)
        ll.addWidget(row(rf, so))
        al.addWidget(left, 0, Qt.AlignmentFlag.AlignTop)

        right, rl = card((18, 18, 18, 18))
        head = QHBoxLayout()
        head.addWidget(label("Your outfits", "h2"))
        self.av_count = label("", "stat")
        head.addWidget(self.av_count)
        head.addStretch(1)
        rl.addLayout(head)
        self.av_msg = label("", "muted")
        rl.addWidget(self.av_msg)
        grid_w = QWidget()
        self.av_grid = FlowLayout(grid_w)
        rl.addWidget(grid_w)
        rl.addStretch(1)
        al.addWidget(right, 1)
        lay.addWidget(self.av_in)
        self.av_in.hide()
        lay.addStretch(1)
        return page

    # ---------- account
    def _restore_session(self):
        cookie = account.load_session()
        if not cookie:
            self._account_ui()
            return
        api.cookie = cookie

        def done(me, err):
            if err:
                if getattr(err, "code", 0) == 401:
                    account.clear_session()
                    api.cookie = None
                self._account_ui()
                return
            self.me = me
            self._account_ui()
            self._avatar_refresh()

        bg(api.me, done)

    def _sign_in(self):
        try:
            dlg = account.LoginDialog(self)
        except Exception:
            QMessageBox.warning(self, config.APP_NAME, "The sign-in window couldn't open on this PC.")
            return
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.cookie:
            return
        api.cookie, api.csrf = dlg.cookie, None

        def done(me, err):
            if err:
                api.cookie = None
                QMessageBox.warning(self, config.APP_NAME, scrub(err))
                return
            try:
                account.save_session(dlg.cookie)
            except Exception:
                pass
            self.me = me
            self._account_ui()
            self._avatar_refresh()
            self.nav_buttons[2].click()

        bg(api.me, done)

    def _sign_out(self):
        account.clear_session()
        api.cookie = api.csrf = None
        self.me = None
        clear_layout(self.av_grid)
        self._account_ui()

    def _account_ui(self):
        signed = self.me is not None
        self.av_out.setVisible(not signed)
        self.av_in.setVisible(signed)
        self.acc_name.setText(self.me["display"] if signed else "Not signed in")
        self.acc_btn.setText("Sign out" if signed else "Sign in")
        if signed:
            self.av_display.setText(self.me["display"])
            self.av_user.setText("@" + self.me["name"])
        else:
            self.avatar_chip.setPixmap(rounded(None, 36))
            self.avatar_chip.setText("R")

    def _account_clicked(self):
        self._sign_out() if self.me else self._sign_in()

    # ---------- avatar + outfits
    def _avatar_refresh(self):
        if not self.me:
            return
        uid = self.me["id"]
        self.av_msg.setText("Loading your outfits...")
        self.av_msg.show()

        def work():
            render, head = api.avatar_render(uid), api.headshot(uid)
            outfits = api.outfits(uid)
            atype = api.avatar_type()
            imgs = api.download_many([render, head])
            return render, head, outfits, atype, imgs

        def done(res, err):
            if err:
                self.av_msg.setText(scrub(err))
                self.av_msg.show()
                return
            render, head, outfits, atype, imgs = res
            if render in imgs:
                self.av_render.setPixmap(rounded(pixmap_from(imgs[render]), 226, 260, radius=12))
            if head in imgs:
                self.avatar_chip.setText("")
                self.avatar_chip.setPixmap(rounded(pixmap_from(imgs[head]), 36, radius=None))
            if atype in self.av_type_btns:
                self.av_type_btns[atype].setChecked(True)
            self._render_outfits(outfits)

        bg(work, done)

    def _refresh_render_only(self):
        if not self.me:
            return
        uid = self.me["id"]

        def work():
            url = api.avatar_render(uid)
            return api.download(url) if url else None

        bg(work, lambda b, e: b and self.av_render.setPixmap(rounded(pixmap_from(b), 226, 260, radius=12)))

    def _render_outfits(self, outfits):
        clear_layout(self.av_grid)
        self.outfit_tiles = {}
        self.av_count.setText(str(len(outfits)))
        self.av_msg.setText("" if outfits else "No saved outfits yet. Save some in the Roblox avatar editor.")
        self.av_msg.setVisible(not outfits)
        for o in outfits:
            tile = Clickable("tile", lambda oid=o["id"]: self._wear(oid))
            tile.setFixedSize(118, 150)
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(8, 8, 8, 8)
            tl.setSpacing(6)
            th_ = QLabel()
            th_.setFixedSize(102, 102)
            th_.setObjectName("gamebig")
            tl.addWidget(th_)
            nm = QLabel()
            nm.setText(elide(o["name"], 100, nm))
            nm.setToolTip(o["name"])
            nm.setStyleSheet("font-weight:600; font-size:12px;")
            nm.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            tl.addWidget(nm)
            tile._thumb, tile._name, tile._title = th_, nm, o["name"]
            self.outfit_tiles[str(o["id"])] = tile
            self.av_grid.addWidget(tile)
        ids = [o["id"] for o in outfits]
        if not ids:
            return

        def work():
            thumbs = api.outfit_thumbs(ids)
            return thumbs, api.download_many(list(thumbs.values()))

        def done(res, err):
            if err or not res:
                return
            thumbs, imgs = res
            for oid, url in thumbs.items():
                t = self.outfit_tiles.get(str(oid))
                if t and url in imgs:
                    t._thumb.setPixmap(rounded(pixmap_from(imgs[url]), 102, radius=10))

        bg(work, done)

    def _wear(self, outfit_id):
        if self.wearing:
            return
        self.wearing = True
        tile = self.outfit_tiles.get(str(outfit_id))
        for t in self.outfit_tiles.values():
            t.setProperty("selected", t is tile)
            t.style().unpolish(t)
            t.style().polish(t)
        if tile:
            tile._name.setText("Wearing...")

        def done(_, err):
            self.wearing = False
            if tile:
                tile._name.setText(elide(tile._title, 100, tile._name))
            if err:
                QMessageBox.warning(self, config.APP_NAME, f"Couldn't wear that outfit: {scrub(err)}")
                return
            self.status_lbl.setText("Outfit changed")
            for ms in (2500, 6000):
                QTimer.singleShot(ms, self._refresh_render_only)

        bg(lambda: api.wear_outfit(outfit_id), done)

    def _set_type(self, t):
        def done(_, err):
            if err:
                QMessageBox.warning(self, config.APP_NAME, scrub(err))
                return
            QTimer.singleShot(2500, self._refresh_render_only)

        bg(lambda: api.set_avatar_type(t), done)
