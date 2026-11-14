"""Desktop + Start Menu shortcuts for Chrome Blox (Windows)."""
import os
import subprocess
import sys
from pathlib import Path

import config

PS = r"""
$sh = New-Object -ComObject WScript.Shell
$places = @()
if ($env:CB_DESKTOP -eq '1') { $places += [Environment]::GetFolderPath('Desktop') }
if ($env:CB_START -eq '1') { $places += [Environment]::GetFolderPath('Programs') }
foreach ($dir in $places) {
    $lnk = $sh.CreateShortcut((Join-Path $dir ($env:CB_NAME + '.lnk')))
    $lnk.TargetPath = $env:CB_TARGET
    $lnk.Arguments = $env:CB_ARGS
    $lnk.WorkingDirectory = $env:CB_WORKDIR
    $lnk.IconLocation = $env:CB_ICON
    $lnk.Description = 'Roblox launcher'
    $lnk.Save()
}
"""


def _target():
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return exe, "", exe.parent, f"{exe},0"
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    script = Path(__file__).resolve().parent / "main.py"
    icon = Path(__file__).resolve().parent.parent / "icon.ico"
    return (pyw if pyw.exists() else py), f'"{script}"', script.parent, (f"{icon},0" if icon.exists() else "")


def create(desktop=True, start_menu=True):
    if os.name != "nt":
        raise RuntimeError("Shortcuts only work on Windows.")
    target, args, workdir, icon = _target()
    env = dict(os.environ, CB_NAME=config.APP_NAME, CB_TARGET=str(target), CB_ARGS=args,
               CB_WORKDIR=str(workdir), CB_ICON=icon,
               CB_DESKTOP="1" if desktop else "0", CB_START="1" if start_menu else "0")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-Command", PS], env=env, capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
    if r.returncode != 0:
        raise RuntimeError("Couldn't make the shortcut.")


def first_run(cfg):
    """Make shortcuts once, the first time the exe is opened."""
    if cfg.get("shortcuts_made") or os.name != "nt" or not getattr(sys, "frozen", False):
        return
    try:
        create()
        cfg["shortcuts_made"] = True
        cfg.save()
    except Exception:
        pass
