"""Small Roblox web API client: servers, thumbnails, games, and (signed in) avatar/outfits."""
import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import config

UA = f"ChromeBlox/{config.APP_VERSION}"


class ApiError(RuntimeError):
    def __init__(self, msg, code=0):
        super().__init__(msg)
        self.code = code


class Api:
    def __init__(self):
        self.cookie = None
        self.csrf = None

    # ------------------------------------------------ core
    def request(self, method, url, body=None, auth=True, timeout=15):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        for attempt in range(2):
            h = {"User-Agent": UA, "Accept": "application/json"}
            if data is not None:
                h["Content-Type"] = "application/json"
            if auth and self.cookie:
                h["Cookie"] = f".ROBLOSECURITY={self.cookie}"
                if method != "GET" and self.csrf:
                    h["X-CSRF-TOKEN"] = self.csrf
            req = urllib.request.Request(url, data=data, headers=h, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                token = e.headers.get("x-csrf-token")
                if e.code == 403 and token and attempt == 0:
                    self.csrf = token
                    continue
                if e.code == 401:
                    raise ApiError("You got signed out, sign in again.", 401)
                if e.code == 429:
                    raise ApiError("Roblox says slow down, try again in a few seconds.", 429)
                raise ApiError(f"Roblox returned an error ({e.code}).", e.code)
            except urllib.error.URLError:
                raise ApiError("Couldn't reach Roblox. Check your internet.")
        raise ApiError("Roblox rejected the request.")

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, body=None, **kw):
        return self.request("POST", url, body if body is not None else {}, **kw)

    @staticmethod
    def download(url, timeout=10):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def download_many(self, urls, workers=16):
        """{url: bytes} for every url that downloads ok."""
        urls = [u for u in dict.fromkeys(urls) if u]
        out = {}

        def one(u):
            try:
                return u, self.download(u)
            except Exception:
                return u, None

        with ThreadPoolExecutor(workers) as ex:
            for u, b in ex.map(one, urls):
                if b:
                    out[u] = b
        return out

    # ------------------------------------------------ account
    def me(self):
        d = self.get("https://users.roblox.com/v1/users/authenticated")
        return {"id": d["id"], "name": d.get("name", ""), "display": d.get("displayName") or d.get("name", "")}

    # ------------------------------------------------ games / servers
    def game(self, place_id):
        uni = self.get(f"https://apis.roblox.com/universes/v1/places/{place_id}/universe", auth=False)["universeId"]
        g = self.get(f"https://games.roblox.com/v1/games?universeIds={uni}", auth=False)["data"][0]
        icon = ""
        try:
            icon = self.get(f"https://thumbnails.roblox.com/v1/games/icons?universeIds={uni}&returnPolicy=PlaceHolder"
                            "&size=150x150&format=Png&isCircular=false", auth=False)["data"][0].get("imageUrl", "")
        except Exception:
            pass
        return {"place_id": str(place_id), "universe": uni, "name": g.get("name", "Roblox"),
                "creator": (g.get("creator") or {}).get("name", ""), "playing": g.get("playing", 0),
                "icon_url": icon}

    def servers(self, place_id, order="Desc", cursor=None):
        q = {"sortOrder": order, "excludeFullGames": "false", "limit": 100}
        if cursor:
            q["cursor"] = cursor
        d = self.get(f"https://games.roblox.com/v1/games/{place_id}/servers/Public?" + urllib.parse.urlencode(q))
        return d.get("data", []), d.get("nextPageCursor")

    def headshots_by_token(self, tokens, size="48x48"):
        """{token: imageUrl}"""
        out = {}
        tokens = list(dict.fromkeys(tokens))
        for i in range(0, len(tokens), 100):
            chunk = tokens[i:i + 100]
            body = [{"requestId": t, "token": t, "type": "AvatarHeadShot", "size": size, "format": "png",
                     "isCircular": False} for t in chunk]
            try:
                d = self.post("https://thumbnails.roblox.com/v1/batch", body, auth=False)
                for item in d.get("data", []):
                    if item.get("imageUrl"):
                        out[item["requestId"]] = item["imageUrl"]
            except Exception:
                pass
        return out

    # ------------------------------------------------ avatar
    def avatar_render(self, user_id, size="420x420"):
        d = self.get(f"https://thumbnails.roblox.com/v1/users/avatar?userIds={user_id}&size={size}"
                     "&format=Png&isCircular=false", auth=False)["data"]
        return d[0].get("imageUrl", "") if d else ""

    def headshot(self, user_id, size="150x150"):
        d = self.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size={size}"
                     "&format=Png&isCircular=false", auth=False)["data"]
        return d[0].get("imageUrl", "") if d else ""

    def avatar_type(self):
        try:
            return self.get("https://avatar.roblox.com/v1/avatar").get("playerAvatarType", "R15")
        except Exception:
            return "R15"

    def set_avatar_type(self, t):
        self.post("https://avatar.roblox.com/v1/avatar/set-player-avatar-type", {"playerAvatarType": t})
        self._redraw()

    def outfits(self, user_id):
        try:
            d = self.get(f"https://avatar.roblox.com/v2/avatar/users/{user_id}/outfits"
                         "?page=1&itemsPerPage=50&isEditable=true")
        except ApiError:
            d = self.get(f"https://avatar.roblox.com/v1/users/{user_id}/outfits"
                         "?page=1&itemsPerPage=50&isEditable=true")
        items = d.get("data", [])
        return [{"id": o["id"], "name": o.get("name", "Outfit")} for o in items if o.get("id")]

    def outfit_thumbs(self, ids, size="150x150"):
        out = {}
        ids = [str(i) for i in ids]
        for i in range(0, len(ids), 50):
            chunk = ",".join(ids[i:i + 50])
            try:
                d = self.get(f"https://thumbnails.roblox.com/v1/users/outfits?userOutfitIds={chunk}&size={size}"
                             "&format=Png&isCircular=false", auth=False)
                for t in d.get("data", []):
                    if t.get("imageUrl"):
                        out[str(t["targetId"])] = t["imageUrl"]
            except Exception:
                pass
        return out

    def wear_outfit(self, outfit_id):
        try:
            d = self.get(f"https://avatar.roblox.com/v3/outfits/{outfit_id}/details")
        except ApiError:
            d = self.get(f"https://avatar.roblox.com/v1/outfits/{outfit_id}/details")

        assets = d.get("assets") or []
        if d.get("playerAvatarType"):
            try:
                self.post("https://avatar.roblox.com/v1/avatar/set-player-avatar-type",
                          {"playerAvatarType": d["playerAvatarType"]})
            except Exception:
                pass
        if d.get("scale"):
            try:
                self.post("https://avatar.roblox.com/v1/avatar/set-scales", d["scale"])
            except Exception:
                pass
        if d.get("bodyColor3s"):
            try:
                self.post("https://avatar.roblox.com/v2/avatar/set-body-colors", d["bodyColor3s"])
            except Exception:
                pass
        elif d.get("bodyColors"):
            try:
                self.post("https://avatar.roblox.com/v1/avatar/set-body-colors", d["bodyColors"])
            except Exception:
                pass

        wear = []
        for a in assets:
            item = {"id": a["id"]}
            if a.get("meta"):
                item["meta"] = a["meta"]
            wear.append(item)
        try:
            self.post("https://avatar.roblox.com/v2/avatar/set-wearing-assets", {"assets": wear})
        except ApiError:
            self.post("https://avatar.roblox.com/v1/avatar/set-wearing-assets",
                      {"assetIds": [a["id"] for a in assets]})
        self._redraw()

    def _redraw(self):
        try:
            self.post("https://avatar.roblox.com/v1/avatar/redraw-thumbnail")
        except Exception:
            pass


api = Api()
