import copy
import json
import os
from pathlib import Path

APP_NAME = "Chrome Blox"
APP_VERSION = "1.4.0"

BASE = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share")) / "ChromeBlox"
VERSIONS = BASE / "Versions"
DOWNLOADS = BASE / "Downloads"
MODS = BASE / "Modifications"
CONFIG_FILE = BASE / "settings.json"

DEFAULTS = {
    # look
    "theme": {"bg": "#16181c", "surface": "#26292f", "accent": "#1bd96a", "text": "#ecf0f1"},
    "bg_image": "",
    "click_sound": True,
    "custom_sound": False,
    "volume": 0.6,
    # roblox
    "current_version": "",
    "multi_instance": False,
    # mods
    "custom_font": "",
    "custom_cursor": "",
    "fflags": {},
    # updates
    "auto_update": True,
    "github_mods": True,
    # overlay
    "overlay": True,
    # discord
    "discord_rpc": False,
    "discord_app_id": "",
    "show_region": True,
}

MODS_README = """Chrome Blox mods folder
=======================

Anything you put in here gets copied over Roblox's own files every time you launch.
Use the same folder layout as the Roblox client, for example:

  content/sounds/ouch.ogg                          -> death sound (put the old oof here)
  content/textures/Cursors/KeyboardMouse/...       -> cursors
  content/sky/...                                  -> skybox textures
  content/fonts/...                                -> fonts

Delete a file here and it goes back to normal next launch.
"""


def ensure_dirs():
    for d in (BASE, VERSIONS, DOWNLOADS, MODS):
        d.mkdir(parents=True, exist_ok=True)
    readme = MODS / "README.txt"
    if not readme.exists():
        readme.write_text(MODS_README, encoding="utf-8")


class Config(dict):
    def __init__(self):
        super().__init__(copy.deepcopy(DEFAULTS))
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.update(data)
        except Exception:
            pass

    def save(self):
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_FILE)
