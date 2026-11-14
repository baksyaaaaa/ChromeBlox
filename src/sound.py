"""Chrome Client's creamy click: synthesized on first run. One sound for every button and event.
Pick your own sound (wav, or mp3/ogg with `pip install miniaudio`) from the Appearance page."""
import array
import math
import os
import shutil
import struct
import sys
import wave

import config

SR = 44100
DEFAULT = config.BASE / "click_creamy.wav"
CUSTOM = config.BASE / "click_custom.wav"
CACHE = config.BASE / "click_play.wav"


def _bloop(f_start, f_end, dur, decay=20.0, glide=40.0):
    n = int(SR * dur)
    out, phase = [], 0.0
    for i in range(n):
        t = i / SR
        freq = f_end + (f_start - f_end) * math.exp(-t * glide)
        phase += 2 * math.pi * freq / SR
        env = (1 - math.exp(-t * 700)) * math.exp(-t * decay)
        out.append((math.sin(phase) + 0.22 * math.sin(2 * phase) + 0.12 * math.sin(0.5 * phase)) * env)
    return out


def make_default(path, gain=0.55):
    buf = _bloop(520, 760, 0.17, decay=24)
    y = 0.0
    for i, v in enumerate(buf):          # warm lowpass
        y += 0.22 * (v - y)
        buf[i] = y
    for delay, fb in ((0.035, 0.30), (0.07, 0.16)):   # creamy echo tail
        d = int(SR * delay)
        buf.extend([0.0] * d)
        for i in range(d, len(buf)):
            buf[i] += buf[i - d] * fb
    scale = gain / max(1e-9, max(abs(v) for v in buf))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v * scale)) * 32767)) for v in buf))


def import_sound(src, max_seconds=3.0):
    """Convert any sound file to a short WAV and use it as the click. Raises RuntimeError on failure."""
    tmp = CUSTOM.with_name("click.tmp.wav")
    try:
        try:
            import miniaudio
        except ImportError:
            miniaudio = None
        if miniaudio is not None:
            dec = miniaudio.decode_file(str(src), output_format=miniaudio.SampleFormat.SIGNED16)
            samples = dec.samples[: int(max_seconds * dec.sample_rate * dec.nchannels)]
            with wave.open(str(tmp), "wb") as w:
                w.setnchannels(dec.nchannels)
                w.setsampwidth(2)
                w.setframerate(dec.sample_rate)
                w.writeframes(samples.tobytes())
        elif str(src).lower().endswith(".wav"):
            with wave.open(str(src), "rb"):
                pass
            shutil.copyfile(src, tmp)
        else:
            raise RuntimeError("For mp3/ogg sounds run:  pip install miniaudio   or pick a .wav file.")
        os.replace(tmp, CUSTOM)
    except RuntimeError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Couldn't read that sound file ({type(e).__name__}).") from e


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
