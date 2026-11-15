"""Self-update from GitHub Releases. Every build GitHub makes becomes release `build-N`;
the exe knows its own N (build_info.py is written by the workflow) and updates to anything newer."""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import config

REPO = "baksyaaaaa/ChromeBlox"
UPDATE_DIR = config.BASE / "update"
UA = f"ChromeBlox/{config.APP_VERSION}"

try:
    from build_info import BUILD
except ImportError:          # running from source
    BUILD = 0


def frozen():
    return getattr(sys, "frozen", False)


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def check():
    """Return {'build': N, 'url': zip_url, 'size': bytes} if a newer build exists, else None."""
    rel = _get_json(f"https://api.github.com/repos/{REPO}/releases/latest")
    m = re.fullmatch(r"build-(\d+)", rel.get("tag_name", ""))
    if not m:
        return None
    n = int(m.group(1))
    if n <= BUILD:
        return None
    asset = next((a for a in rel.get("assets", []) if a.get("name") == "ChromeBlox.zip"), None)
    if not asset:
        return None
    return {"build": n, "url": asset["browser_download_url"], "size": asset.get("size", 0)}


def download(info, on_progress=lambda p: None):
    """Download + unpack the new build. Returns the folder holding the new ChromeBlox.exe."""
    shutil.rmtree(UPDATE_DIR, ignore_errors=True)
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    zpath = UPDATE_DIR / "ChromeBlox.zip"
    req = urllib.request.Request(info["url"], headers={"User-Agent": UA})
    total = info.get("size") or 1
    got = 0
    with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            on_progress(min(99, int(got * 100 / total)))
    new = UPDATE_DIR / "new"
    with zipfile.ZipFile(zpath) as z:
        z.extractall(new)
    zpath.unlink(missing_ok=True)
    exe = next(new.rglob("ChromeBlox.exe"), None)
    if not exe:
        raise RuntimeError("The update download looks broken.")
    (UPDATE_DIR / "ready.json").write_text(json.dumps({"build": info["build"], "dir": str(exe.parent)}))
    on_progress(100)
    return exe.parent


def ready():
    """A downloaded update waiting to be installed, or None."""
    try:
        d = json.loads((UPDATE_DIR / "ready.json").read_text())
        if d["build"] > BUILD and (Path(d["dir"]) / "ChromeBlox.exe").exists():
            return d
    except Exception:
        pass
    return None


def install_and_restart(d):
    """Swap the app folder for the new one after we exit, then start the new version."""
    app_dir = Path(sys.executable).parent
    bat = UPDATE_DIR / "apply.bat"
    bat.write_text(f"""@echo off
:wait
tasklist /FI "PID eq {os.getpid()}" | find "{os.getpid()}" >nul && (timeout /t 1 /nobreak >nul & goto wait)
robocopy "{d['dir']}" "{app_dir}" /MIR /R:3 /W:1 /NFL /NDL /NJH /NJS >nul
start "" "{app_dir / 'ChromeBlox.exe'}"
rmdir /S /Q "{UPDATE_DIR / 'new'}"
del "{UPDATE_DIR / 'ready.json'}"
""", encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True)
