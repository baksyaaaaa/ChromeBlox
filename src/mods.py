"""Applies mods on top of a clean Roblox install, and undoes the last batch first."""
import json
import shutil
from pathlib import Path

import config

STATE = ".chromeblox_mods.json"
ORIG = ".chromeblox_orig"
FONT_FAMILIES = Path("content/fonts/families")
CURSOR_DIR = Path("content/textures/Cursors/KeyboardMouse")


class _Overlay:
    def __init__(self, root):
        self.root = root
        self.overwritten = []
        self.added = []

    def put_bytes(self, rel, data):
        rel = Path(rel)
        key = rel.as_posix()
        target = self.root / rel
        if key not in self.overwritten and key not in self.added:
            if target.exists():
                backup = self.root / ORIG / rel
                if not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                self.overwritten.append(key)
            else:
                self.added.append(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def put_file(self, rel, src):
        self.put_bytes(rel, Path(src).read_bytes())


def revert(root):
    root = Path(root)
    state_file = root / STATE
    if not state_file.exists():
        return
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    for key in state.get("overwritten", []):
        backup = root / ORIG / key
        if backup.exists():
            shutil.copy2(backup, root / key)
    for key in state.get("added", []):
        (root / key).unlink(missing_ok=True)
    state_file.unlink(missing_ok=True)


def apply_mods(root, cfg):
    root = Path(root)
    revert(root)
    ov = _Overlay(root)

    # custom font: every font family points at one file
    font = cfg.get("custom_font")
    if font and Path(font).is_file():
        name = "CustomFont.ttf"   # Roblox only loads it under a .ttf name, even for .otf files (same as Bloxstrap)
        ov.put_file(Path("content/fonts") / name, font)
        fam_dir = root / FONT_FAMILIES
        if fam_dir.is_dir():
            for fj in fam_dir.glob("*.json"):
                try:
                    data = json.loads(fj.read_text(encoding="utf-8"))
                except Exception:
                    continue
                faces = data.get("faces") or []
                for face in faces:
                    face["assetId"] = f"rbxasset://fonts/{name}"
                if faces:
                    ov.put_bytes(FONT_FAMILIES / fj.name, json.dumps(data, indent=2).encode("utf-8"))

    # custom cursor
    cursor = cfg.get("custom_cursor")
    if cursor and Path(cursor).is_file():
        for n in ("ArrowCursor.png", "ArrowFarCursor.png"):
            ov.put_file(CURSOR_DIR / n, cursor)

    # user's mods folder goes last so it wins
    if config.MODS.is_dir():
        for f in sorted(config.MODS.rglob("*")):
            if f.is_file() and not f.name.startswith(".") and f.name.lower() != "readme.txt":
                ov.put_file(f.relative_to(config.MODS), f)

    # fast flags
    flags = cfg.get("fflags") or {}
    if flags:
        ov.put_bytes("ClientSettings/ClientAppSettings.json", json.dumps(flags, indent=2).encode("utf-8"))

    (root / STATE).write_text(json.dumps({"overwritten": ov.overwritten, "added": ov.added}), encoding="utf-8")
