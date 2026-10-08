# -*- coding: utf-8 -*-
"""Sound sources for the acoustic simulation.

Every source is a continuous-time signal s(t) (float, 1.0 = full scale at 1 m)
that can be evaluated at arbitrary sample times, which is what fractional
propagation delays need.  `active(t)` is the ground-truth "someone is talking"
flag used to score the VAD / wake logic.
"""
import math
import wave

import numpy as np

SR = 16000


class Source:
    name = "source"
    pos = (2.0, 0.0, 0.25)   # world position, metres

    def signal(self, t):
        """t: np.ndarray of times [s] -> np.ndarray of samples (float)."""
        raise NotImplementedError

    def active(self, t0, t1):
        """Ground truth: is the source emitting speech-like energy in [t0, t1)?"""
        return True


class WavSource(Source):
    """Loops a user-supplied WAV file (first channel)."""

    def __init__(self, path, gain=1.0, loop=True, name="wav", pos=None, vad_threshold=0.01):
        w = wave.open(path)
        n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
        if sw != 2:
            raise ValueError("only 16-bit WAV supported")
        x = np.frombuffer(raw, dtype="<i2").reshape(-1, ch)[:, 0].astype(np.float32) / 32768.0
        if sr != SR:  # linear resample
            t_src = np.arange(len(x)) / sr
            t_dst = np.arange(int(len(x) * SR / sr)) / SR
            x = np.interp(t_dst, t_src, x).astype(np.float32)
        self.x = x * gain
        self.loop = loop
        self.name = name
        self.dur = len(self.x) / SR
        self.vad_threshold = vad_threshold
        # per-10 ms RMS for the ground-truth flag
        blk = SR // 100
        nblk = len(self.x) // blk
        self.rms = np.sqrt((self.x[:nblk * blk].reshape(nblk, blk) ** 2).mean(axis=1))
        if pos is not None:
            self.pos = pos

    def signal(self, t):
        idx = t * SR
        if self.loop:
            idx = np.mod(idx, len(self.x))
        i0 = np.floor(idx).astype(np.int64)
        frac = (idx - i0).astype(np.float32)
        i1 = (i0 + 1) % len(self.x) if self.loop else np.minimum(i0 + 1, len(self.x) - 1)
        valid = (i0 >= 0) & (i0 < len(self.x))
        i0c = np.clip(i0, 0, len(self.x) - 1)
        out = self.x[i0c] * (1 - frac) + self.x[i1] * frac
        return np.where(valid, out, 0.0).astype(np.float32)

    def active(self, t0, t1):
        if self.loop:
            t0, t1 = t0 % self.dur, t0 % self.dur + (t1 - t0)
        b0, b1 = int(t0 * 100), max(int(t0 * 100) + 1, int(math.ceil(t1 * 100)))
        seg = self.rms[b0 % len(self.rms):b1 % len(self.rms)] if b1 % len(self.rms) > b0 % len(self.rms) else self.rms[b0 % len(self.rms):]
        return bool(len(seg) and seg.max() > self.vad_threshold)


class ToneSource(Source):
    def __init__(self, freq=440.0, amp=0.3, name="tone", pos=None):
        self.freq, self.amp, self.name = freq, amp, name
        if pos is not None:
            self.pos = pos

    def signal(self, t):
        return (self.amp * np.sin(2 * np.pi * self.freq * t)).astype(np.float32)


class NoiseSource(Source):
    """Band-limited-ish white noise from a long pre-generated table (deterministic)."""

    def __init__(self, amp=0.05, seed=1, name="noise", pos=None, seconds=30.0):
        rng = np.random.default_rng(seed)
        self.x = (rng.standard_normal(int(seconds * SR)) * amp).astype(np.float32)
        self.name = name
        if pos is not None:
            self.pos = pos

    def signal(self, t):
        idx = np.mod(t * SR, len(self.x))
        i0 = np.floor(idx).astype(np.int64)
        frac = (idx - i0).astype(np.float32)
        return self.x[i0] * (1 - frac) + self.x[(i0 + 1) % len(self.x)] * frac

    def active(self, t0, t1):
        return False   # noise is never "speech"


class SyntheticSource(NoiseSource):
    """Deterministic broadband stimulus; contains no recorded speech."""

    def __init__(self, amp=.15, seed=17, name="synthetic", pos=None):
        super().__init__(amp=1, seed=seed, name=name, pos=pos, seconds=4)
        spectrum = np.fft.rfft(self.x)
        frequencies = np.fft.rfftfreq(len(self.x), 1 / SR)
        spectrum[(frequencies < 300) | (frequencies > 1800)] = 0
        signal = np.fft.irfft(spectrum, n=len(self.x))
        self.x = (signal * amp / np.sqrt(np.mean(signal ** 2))).astype(np.float32)

    def active(self, t0, t1):
        return True


class Scheduled(Source):
    """Gate another source with on/off windows: [(t_on, t_off), ...] seconds."""

    def __init__(self, inner, windows, name=None):
        self.inner, self.windows = inner, list(windows)
        self.name = name or inner.name
        self.pos = inner.pos

    def _gate(self, t):
        g = np.zeros_like(t, dtype=np.float32)
        for a, b in self.windows:
            g += ((t >= a) & (t < b)).astype(np.float32)
        return np.minimum(g, 1.0)

    def signal(self, t):
        return self.inner.signal(t) * self._gate(t)

    def active(self, t0, t1):
        return any(a < t1 and b > t0 for a, b in self.windows) and self.inner.active(t0, t1)


def make_source(spec):
    """Build a source from a scenario dict: {"type": "wav"|"tone"|"noise", "pos": [x,y,z], ...,
    "windows": [[on, off], ...]} (windows optional)."""
    kind = spec.get("type", "tone")
    pos = tuple(spec.get("pos", Source.pos))
    name = spec.get("name", kind)
    if kind == "wav":
        src = WavSource(spec["path"], gain=spec.get("gain", 1.0), name=name, pos=pos)
    elif kind == "synthetic":
        src = SyntheticSource(amp=spec.get("amp", .15), seed=spec.get("seed", 17),
                              name=name, pos=pos)
    elif kind == "noise":
        src = NoiseSource(amp=spec.get("amp", 0.05), seed=spec.get("seed", 1), name=name, pos=pos)
    else:
        src = ToneSource(freq=spec.get("freq", 440.0), amp=spec.get("amp", 0.3), name=name, pos=pos)
    if spec.get("windows"):
        src = Scheduled(src, spec["windows"], name=name)
    return src
