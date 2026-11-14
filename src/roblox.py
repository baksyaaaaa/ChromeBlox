"""Downloads the official Roblox client, keeps it updated and launches it."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import config

UA = f"ChromeBlox/{config.APP_VERSION}"
CLIENT_VERSION_URL = "https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer"
CDN = "https://setup.rbxcdn.com"

# where each package zip gets extracted inside the client folder
PACKAGE_MAP = {
    "RobloxApp.zip": "",
    "redist.zip": "",
    "WebView2.zip": "",
    "shaders.zip": "shaders",
    "ssl.zip": "ssl",
    "content-avatar.zip": "content/avatar",
    "content-configs.zip": "content/configs",
    "content-fonts.zip": "content/fonts",
    "content-sky.zip": "content/sky",
    "content-sounds.zip": "content/sounds",
    "content-textures2.zip": "content/textures",
    "content-models.zip": "content/models",
    "content-platform-fonts.zip": "PlatformContent/pc/fonts",
    "content-platform-dictionaries.zip": "PlatformContent/pc/shared_compression_dictionaries",
    "content-terrain.zip": "PlatformContent/pc/terrain",
    "content-textures3.zip": "PlatformContent/pc/textures",
    "extracontent-luapackages.zip": "ExtraContent/LuaPackages",
    "extracontent-translations.zip": "ExtraContent/translations",
    "extracontent-models.zip": "ExtraContent/models",
    "extracontent-textures.zip": "ExtraContent/textures",
    "extracontent-places.zip": "ExtraContent/places",
}
SKIP_PACKAGES = {"WebView2RuntimeInstaller.zip"}

APP_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<Settings>
\t<ContentFolder>content</ContentFolder>
\t<BaseUrl>http://www.roblox.com</BaseUrl>
</Settings>
"""

PLAYER_EXE = "RobloxPlayerBeta.exe"


# ---------------------------------------------------------------- http
def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_json(url, timeout=15):
    return json.loads(http_get(url, timeout).decode("utf-8"))


# ---------------------------------------------------------------- versions
def latest_version():
    return http_json(CLIENT_VERSION_URL)["clientVersionUpload"]


def client_dir(version):
    return config.VERSIONS / version


def is_installed(version):
    d = client_dir(version)
    return bool(version) and (d / ".installed").exists() and (d / PLAYER_EXE).exists()


def parse_manifest(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines or lines[0] != "v0":
        raise RuntimeError("Roblox changed their package format, launcher needs an update.")
    body = lines[1:]
    pkgs = []
    for i in range(0, len(body) - 3, 4):
        name, md5, packed, size = body[i:i + 4]
        pkgs.append({"name": name, "md5": md5.lower(), "packed": int(packed), "size": int(size)})
    return pkgs


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url, dest, md5, on_bytes):
    tmp = dest.with_suffix(".part")
    last_err = None
    for _ in range(3):
        try:
            h = hashlib.md5()
            got = 0
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    on_bytes(got)
            if h.hexdigest() != md5:
                raise RuntimeError("download got corrupted")
            os.replace(tmp, dest)
            return
        except Exception as e:  # retry
            last_err = e
            time.sleep(1)
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"Couldn't download {dest.name}: {last_err}")


def _extract(zip_path, target):
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/").lstrip("/")
            if not name or name.endswith("/") or ".." in name.split("/"):
                continue
            out = target / name
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)


def install(version, on_progress=lambda p: None, on_status=lambda s: None):
    """Make sure `version` is installed, return its folder."""
    dest = client_dir(version)
    if is_installed(version):
        return dest

    on_status("Getting Roblox package list…")
    manifest = parse_manifest(http_get(f"{CDN}/{version}-rbxPkgManifest.txt").decode("utf-8"))
    pkgs = [p for p in manifest if p["name"].endswith(".zip") and p["name"] not in SKIP_PACKAGES]
    total = sum(p["packed"] for p in pkgs) or 1

    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    done = 0
    for p in pkgs:
        cached = config.DOWNLOADS / p["md5"]
        if not (cached.exists() and _md5(cached) == p["md5"]):
            on_status(f"Downloading Roblox… ({p['name']})")
            base = done
            _download(f"{CDN}/{version}-{p['name']}", cached, p["md5"],
                      lambda n, base=base: on_progress(min(99, int((base + n) * 100 / total))))
        done += p["packed"]
        on_progress(min(99, int(done * 100 / total)))
        on_status(f"Installing… ({p['name']})")
        _extract(cached, dest / PACKAGE_MAP.get(p["name"], ""))

    (dest / "AppSettings.xml").write_text(APP_SETTINGS, encoding="utf-8")
    if not (dest / PLAYER_EXE).exists():
        raise RuntimeError("Roblox install looks broken (player exe missing). Try Reinstall in Settings.")
    (dest / ".installed").write_text(str(time.time()), encoding="utf-8")
    on_progress(100)
    return dest


def cleanup_old(keep):
    if not config.VERSIONS.exists():
        return
    for d in config.VERSIONS.iterdir():
        if d.is_dir() and d.name != keep:
            shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- launching
_mutex = None


def launch(folder, uri=None, multi_instance=False):
    global _mutex
    if multi_instance and os.name == "nt" and _mutex is None:
        import ctypes
        # owning this first stops Roblox from closing other open windows
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "ROBLOX_singletonMutex")
    args = [str(Path(folder) / PLAYER_EXE), uri or "--app"]
    return subprocess.Popen(args, cwd=str(folder))


# ---------------------------------------------------------------- protocol (website "Play" button)
SCHEMES = ("roblox-player", "roblox")


def launcher_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    exe = pyw if pyw.exists() else py
    return f'"{exe}" "{Path(__file__).resolve().parent / "main.py"}"'


def register_protocols():
    import winreg
    cmd = launcher_command() + ' "%1"'
    for scheme in SCHEMES:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{scheme}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL: Roblox Protocol")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{scheme}\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)


def protocols_registered():
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\roblox-player\shell\open\command") as k:
            value, _ = winreg.QueryValueEx(k, "")
        return launcher_command().lower() in value.lower()
    except OSError:
        return False
