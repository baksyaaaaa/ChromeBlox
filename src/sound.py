"""One creamy click sound for every button (drop your own .wav in from the Look tab)."""
import array
import math
import os
import struct
import sys
import wave

import config

DEFAULT = config.BASE / "click_default.wav"
CUSTOM = config.BASE / "click_custom.wav"
CACHE = config.BASE / "click_play.wav"


def make_default(path):
    sr = 44100
    n = int(sr * 0.11)
    phase = 0.0
    out = bytearray()
    for i in range(n):
        t = i / sr
        freq = 420 + 520 * math.exp(-t * 38)          # soft downward "bloop"
        phase += 2 * math.pi * freq / sr
        env = (1 - math.exp(-t * 700)) * math.exp(-t * 42)
        s = math.sin(phase) * 0.55 + math.sin(phase * 2) * 0.12 * math.exp(-t * 90)
        out += struct.pack("<h", int(max(-1.0, min(1.0, s * env)) * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(out))


class Clicker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.path = DEFAULT
        self.rebuild()

    def source(self):
        return CUSTOM if self.cfg.get("custom_sound") and CUSTOM.exists() else DEFAULT

    def rebuild(self):
        if not DEFAULT.exists():
            make_default(DEFAULT)
        src = self.source()
        vol = max(0.0, min(1.0, float(self.cfg.get("volume", 0.6))))
        try:
            with wave.open(str(src), "rb") as r:
                params = r.getparams()
                data = r.readframes(r.getnframes())
            if params.sampwidth != 2:
                self.path = src
                return
            a = array.array("h")
            a.frombytes(data)
            if sys.byteorder == "big":
                a.byteswap()
            a = array.array("h", (max(-32768, min(32767, int(s * vol))) for s in a))
            if sys.byteorder == "big":
                a.byteswap()
            with wave.open(str(CACHE), "wb") as w:
                w.setparams(params)
                w.writeframes(a.tobytes())
            self.path = CACHE
        except Exception:
            self.path = src

    def play(self):
        if not self.cfg.get("click_sound", True) or os.name != "nt":
            return
        try:
            import winsound
            winsound.PlaySound(str(self.path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass
