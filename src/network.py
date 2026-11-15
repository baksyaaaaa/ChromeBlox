"""Read-only Wi-Fi status for the Settings page."""
import os
import re
import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def wifi_status():
    """{'state','ssid','signal'} or None if there's no Wi-Fi adapter."""
    if os.name != "nt":
        return None
    r = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True,
                       timeout=10, creationflags=NO_WINDOW)
    out = r.stdout or ""
    if r.returncode != 0 or "no wireless interface" in out.lower():
        return None

    def field(name):
        m = re.search(rf"^\s*{name}\s*:\s*(.+)$", out, re.M | re.I)
        return m.group(1).strip() if m else ""

    return {"state": field("State"), "ssid": field("SSID"), "signal": field("Signal")}
