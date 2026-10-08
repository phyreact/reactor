# -*- coding: utf-8 -*-
"""Behavioural twin of the ReSpeaker XVF3800 as the XIAO sees it.

Two faces, both taken from what the real board answered on the bench (2026-09-28):
  * I2C control protocol at 0x2c: read = header [resid, cmd|0x80, len+1] then re-read
    until the status byte stops saying RETRY (64); write = [resid, cmd, len, payload].
    Status 0 OK, 64 RETRY, 65 unknown command, 66 payload length wrong.  The parameter
    table below holds the values read from board ...139 on I2S slave v1.0.8 firmware.
  * I2S: 32-bit slots, L = ASR beam (category 8,0), R = comms beam (7,3) about 5 dB
    lower, both derived here from the 4 simulated mics with a delay-and-sum beam
    steered at the estimated DOA.  DOA_VALUE (20,18) = uint16 azimuth + uint16 speech.
Firmware mode "usb" mimics the 6ch USB firmware: it drives BCLK itself (~1.03 MHz)
and does not answer on I2C -- exactly the situation that made two I2S masters fight.
"""
import math
import struct
import threading

import numpy as np

from ..acoustics.doa import HOP, NFFT, SR, DoaEstimator

RETRY, OK, ERR_CMD, ERR_LEN = 64, 0, 65, 66


def _f32(v): return struct.pack("<f", v)
def _u8(*v): return bytes(v)
def _u32(*v): return b"".join(struct.pack("<I", x) for x in v)
def _i32(v): return struct.pack("<i", v)


class VirtualXVF3800:
    def __init__(self, firmware="i2s", world=None, vad_dbfs=-45.0, out_gain=1.0):
        self.firmware = firmware
        self.world = world                      # AudioWorld, for beamforming geometry
        self.lock = threading.Lock()
        self.vad_thr = 10 ** (vad_dbfs / 20.0)
        self.out_gain = out_gain
        self.doa_deg, self.speech, self.doa_valid = 0, False, False
        self.est = DoaEstimator()
        self._buf = np.zeros((0, 4), dtype=np.float32)
        self._rms_hist = []
        self.agc_gain = 24.3
        self.retry_left = {}                    # (resid,cmd) -> RETRY answers still to give
        # (resid, cmd): [name, payload bytes, rw, live]
        self.params = {
            (48, 0): ["VERSION", _u8(1, 0, 8), "ro", False],
            (48, 1): ["BLD_MSG", b"intdev-lr16-sqr-i2c".ljust(50, b"\0"), "ro", False],
            (48, 8): ["USB_BIT_DEPTH", _u8(16, 16), "rw", False],
            (48, 9): ["SAVE_CONFIGURATION", _u8(0), "wo", False],
            (48, 10): ["CLEAR_CONFIGURATION", _u8(0), "wo", False],
            (35, 0): ["AUDIO_MGR_MIC_GAIN", _f32(90.0), "rw", False],
            (35, 1): ["AUDIO_MGR_REF_GAIN", _f32(1.0), "rw", False],
            (35, 14): ["AUDIO_MGR_OP_UPSAMPLE", _u8(0, 0), "rw", False],
            (35, 15): ["AUDIO_MGR_OP_L", _u8(8, 0), "rw", False],
            (35, 19): ["AUDIO_MGR_OP_R", _u8(7, 3), "rw", False],
            (35, 23): ["AUDIO_MGR_OP_ALL", _u8(8, 0, 1, 0, 1, 2, 7, 3, 1, 1, 1, 3), "rw", False],
            (17, 10): ["PP_AGCONOFF", _i32(1), "rw", False],
            (17, 11): ["PP_AGCMAXGAIN", _f32(64.0), "rw", False],
            (17, 13): ["PP_AGCGAIN", _f32(24.3), "rw", True],
            (33, 35): ["AEC_ASROUTONOFF", _i32(1), "rw", False],
            (33, 75): ["AEC_AZIMUTH_VALUES", _f32(0.0) * 4, "ro", True],
            (20, 12): ["LED_EFFECT", _u8(4), "rw", False],
            (20, 13): ["LED_BRIGHTNESS", _u8(25), "rw", False],
            (20, 14): ["LED_GAMMIFY", _u8(1), "rw", False],
            (20, 15): ["LED_SPEED", _u8(8), "rw", False],
            (20, 16): ["LED_COLOR", _u32(0x2614), "rw", False],
            (20, 17): ["LED_DOA_COLOR", _u32(0, 0x2614), "rw", False],
            (20, 18): ["DOA_VALUE", struct.pack("<HH", 0, 0), "ro", True],
            (20, 19): ["LED_RING_COLOR", _u32(*([0] * 12)), "rw", False],
        }
        self.unsupported = {(48, 11): ERR_LEN, (48, 12): ERR_CMD}   # AIC3104 levels, as observed
        self.saved = 0
        self.writes = []

    # ---- electrical facts the XIAO probes ------------------------------------------
    def i2c_present(self):
        return self.firmware == "i2s"

    def bclk_hz(self):
        return 0 if self.firmware == "i2s" else 1_032_500

    # ---- I2C control protocol -----------------------------------------------------
    def read(self, resid, cmd, length):
        """One host read attempt. Returns (status, payload). Mirrors the bench: live
        values answer RETRY a few times first, static ones answer at once."""
        with self.lock:
            key = (resid, cmd)
            if key in self.unsupported:
                return self.unsupported[key], b"\0" * length
            if key not in self.params:
                return ERR_CMD, b"\0" * length
            name, val, rw, live = self.params[key]
            if length != len(val):
                return ERR_LEN, b"\0" * length
            if live:
                left = self.retry_left.get(key)
                if left is None:
                    left = 9 if name == "PP_AGCGAIN" else 0
                if left > 0:
                    self.retry_left[key] = left - 1
                    return RETRY, b"\0" * length
                self.retry_left.pop(key, None)
                if name == "DOA_VALUE":
                    val = struct.pack("<HH", int(self.doa_deg) % 360, 1 if self.speech else 0)
                elif name == "PP_AGCGAIN":
                    val = _f32(self.agc_gain)
                elif name == "AEC_AZIMUTH_VALUES":
                    val = _f32(math.radians(self.doa_deg)) * 4
            return OK, bytes(val)

    def write(self, resid, cmd, payload):
        with self.lock:
            key = (resid, cmd)
            if key in self.unsupported or key not in self.params:
                return ERR_CMD
            name, val, rw, live = self.params[key]
            if rw == "ro":
                return ERR_CMD
            if len(payload) != len(val):
                return ERR_LEN
            self.writes.append((name, bytes(payload)))
            if name == "SAVE_CONFIGURATION":
                self.saved += 1
            elif name == "CLEAR_CONFIGURATION":
                self.__init__(self.firmware, self.world)
            else:
                self.params[key][1] = bytes(payload)
            return OK

    def param(self, name):
        for (r, c), (n, v, rw, live) in self.params.items():
            if n == name:
                return v
        return None

    # ---- audio: 4 mics in -> 2 I2S words out -------------------------------------
    def process_block(self, mics):
        """mics: float32 (n,4), 1.0 = full scale. Returns (L, R) int32 arrays (n,)."""
        n = mics.shape[0]
        # DOA estimator: 512-sample frames at 50% overlap
        self._buf = np.vstack([self._buf, mics]) if len(self._buf) else mics.copy()
        while len(self._buf) >= NFFT:
            self.est.push(self._buf[:NFFT])
            self._buf = self._buf[HOP:]
            res = self.est.result()
            if res and res["valid"]:
                self.doa_deg, self.doa_valid = res["deg"], True
            elif res:
                self.doa_valid = False
        # beam toward the current estimate (falls back to the last valid angle)
        if self.world is not None:
            beam = self.world.beamform(mics, self.doa_deg)
        else:
            beam = mics.mean(axis=1)
        # simple energy VAD over the last 100 ms
        self._rms_hist.append(float(np.sqrt(np.mean(beam ** 2)) + 1e-12))
        self._rms_hist = self._rms_hist[-10:]
        self.speech = max(self._rms_hist) > self.vad_thr
        g = self.out_gain
        L = np.clip(beam * g, -1.0, 1.0)
        R = np.clip(beam * g * 0.56, -1.0, 1.0)          # comms path sits ~5 dB below ASR on the bench
        if self.param("LED_EFFECT"):
            pass
        return (L * 2147483647.0).astype(np.int32), (R * 2147483647.0).astype(np.int32)
