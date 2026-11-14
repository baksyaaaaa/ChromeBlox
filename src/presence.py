"""Watches the Roblox log to know what game you're in -> Now Playing card + Discord status."""
import asyncio
import os
import re
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

import roblox

LOG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Roblox" / "logs"
JOIN_RE = re.compile(r"! Joining game '([0-9a-fA-F\-]+)' place (\d+) at ([\d\.]+)")
UDMUX_RE = re.compile(r"UDMUX Address = ([\d\.]+)")
LEAVE_RE = re.compile(r"Time to disconnect replication data|Disconnection Notification")


def game_info(place_id):
    info = {"place_id": place_id, "name": "Roblox", "creator": "", "icon_url": "", "icon": b""}
    try:
        uni = roblox.http_json(f"https://apis.roblox.com/universes/v1/places/{place_id}/universe")["universeId"]
        g = roblox.http_json(f"https://games.roblox.com/v1/games?universeIds={uni}")["data"][0]
        info["name"] = g.get("name") or "Roblox"
        info["creator"] = (g.get("creator") or {}).get("name", "")
        t = roblox.http_json(
            f"https://thumbnails.roblox.com/v1/games/icons?universeIds={uni}"
            "&returnPolicy=PlaceHolder&size=512x512&format=Png&isCircular=false")["data"][0]
        info["icon_url"] = t.get("imageUrl") or ""
        if info["icon_url"]:
            info["icon"] = roblox.http_get(info["icon_url"], timeout=10)
    except Exception:
        pass
    return info


def region_for(ip):
    try:
        d = roblox.http_json(f"https://ipinfo.io/{ip}/json", timeout=8)
        parts = [d.get("city"), d.get("country")]
        return ", ".join(p for p in parts if p)
    except Exception:
        return ""


class ActivityWatcher(QObject):
    joined = Signal(dict)
    updated = Signal(dict)
    left = Signal()
    closed = Signal()

    def __init__(self, cfg, proc):
        super().__init__()
        self.cfg = cfg
        self.proc = proc
        self.started_at = time.time()
        self._stop = False
        self._rpc = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop = True

    def running(self):
        return self.proc.poll() is None

    # ---------- discord
    def _rpc_connect(self):
        app_id = (self.cfg.get("discord_app_id") or "").strip()
        if not (self.cfg.get("discord_rpc") and app_id):
            return
        try:
            from pypresence import Presence
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._rpc = Presence(app_id, loop=loop)
            self._rpc.connect()
        except Exception:
            self._rpc = None

    def _rpc_set(self, game, start):
        if not self._rpc:
            return
        try:
            kw = dict(details=game["name"][:128], large_text=game["name"][:128], start=int(start),
                      buttons=[{"label": "View game", "url": f"https://www.roblox.com/games/{game['place_id']}"}])
            state = f"by {game['creator']}" if game.get("creator") else "Playing"
            if game.get("region"):
                state = f"Server: {game['region']}"
            kw["state"] = state[:128]
            if game.get("icon_url"):
                kw["large_image"] = game["icon_url"]
            self._rpc.update(**kw)
        except Exception:
            pass

    def _rpc_clear(self):
        if self._rpc:
            try:
                self._rpc.clear()
            except Exception:
                pass

    # ---------- log tailing
    def _find_log(self):
        deadline = time.time() + 60
        while time.time() < deadline and not self._stop and self.running():
            try:
                logs = [p for p in LOG_DIR.glob("*.log")
                        if "Player" in p.name and p.stat().st_mtime >= self.started_at - 5]
                if logs:
                    return max(logs, key=lambda p: p.stat().st_mtime)
            except OSError:
                pass
            time.sleep(1)
        return None

    def _run(self):
        self._rpc_connect()
        log = self._find_log()
        f = open(log, encoding="utf-8", errors="ignore") if log else None
        game = None
        start = time.time()
        try:
            while not self._stop and self.running():
                line = f.readline() if f else ""
                if not line:
                    time.sleep(0.5)
                    continue
                m = JOIN_RE.search(line)
                if m:
                    game = game_info(m.group(2))
                    game["region"] = ""
                    start = time.time()
                    self.joined.emit(dict(game))
                    self._rpc_set(game, start)
                    continue
                m = UDMUX_RE.search(line)
                if m and game is not None and self.cfg.get("show_region", True):
                    game["region"] = region_for(m.group(1))
                    self.updated.emit(dict(game))
                    self._rpc_set(game, start)
                    continue
                if game is not None and LEAVE_RE.search(line):
                    game = None
                    self._rpc_clear()
                    self.left.emit()
        finally:
            if f:
                f.close()
            self._rpc_clear()
            if self._rpc:
                try:
                    self._rpc.close()
                except Exception:
                    pass
            self.closed.emit()
