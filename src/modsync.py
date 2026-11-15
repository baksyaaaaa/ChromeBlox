"""Keeps the repo's mods/ folder synced to this PC. Add, change or delete files in mods/ on GitHub
and the launcher mirrors it before the next launch. Your own mods folder is never touched."""
import json
import urllib.parse
import urllib.request

import config
from updater import REPO, UA

GITHUB_MODS = config.BASE / "GitHubMods"
STATE = GITHUB_MODS / ".sync.json"


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def sync(on_status=lambda s: None):
    """Returns (changed, removed). Raises on network errors (callers just skip the sync then)."""
    tree = json.loads(_get(f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"))
    remote = {t["path"][len("mods/"):]: t["sha"] for t in tree.get("tree", [])
              if t.get("type") == "blob" and t["path"].startswith("mods/")
              and not t["path"].lower().endswith(("readme.md", ".gitkeep"))}
    try:
        local = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        local = {}

    GITHUB_MODS.mkdir(parents=True, exist_ok=True)
    changed = removed = 0
    for rel, sha in remote.items():
        target = GITHUB_MODS / rel
        if local.get(rel) == sha and target.exists():
            continue
        on_status(f"Downloading mod: {rel}")
        url = f"https://raw.githubusercontent.com/{REPO}/main/mods/{urllib.parse.quote(rel)}"
        data = _get(url, timeout=60)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        local[rel] = sha
        changed += 1
    for rel in list(local):
        if rel not in remote:
            (GITHUB_MODS / rel).unlink(missing_ok=True)
            del local[rel]
            removed += 1
    STATE.write_text(json.dumps(local, indent=1), encoding="utf-8")
    return changed, removed
