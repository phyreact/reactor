# -*- coding: utf-8 -*-
"""Behavioural twin of the XIAO ESP32-S3 bridge firmware (main.c, v0.3).

Same interfaces the real board exposes to the ZERO, so the ZERO-side software
(xiao_bridge_daemon.py, cdc.py, micscope.py, on_wake.sh) runs unchanged:
  * CDC control port  -> a pty, symlinked at a by-id style path
                         (…/usb-Reactor_prototype_XIAO_ReSpeaker_Audio_<MAC>-if03)
  * USB audio IN      -> a UNIX stream socket delivering raw S16LE stereo 16 kHz
                         (sim_arecord.py turns it into `arecord -t raw` stdout)
  * CDC commands and JSON shapes copied from main.c: ping status log i2s_on i2s_off
    i2s_peek i2c_txrx i2c_read vad vad_silence mic_mute speaker_mute reboot bootloader help
  * events {"event":"wake","doa":N,"uptime_ms":T} / {"event":"silence",...}
Behaviour kept faithful on purpose: the BCLK probe at boot (I2S stays off when the
XMOS is on USB firmware), the 300 ms VAD debounce and 30 s silence timer, the RETRY
loop on I2C reads, events written only while the port is open (so a listener that
opens late gets the backlog burst, like the real CDC FIFO).
"""
import errno
import json
import os
import pty
import socket
import struct
import threading
import time

import numpy as np

from ..acoustics.doa import SR

FW_VERSION = "xiao-uac2-cdc-0.2"
MAC = "020000000001"  # Synthetic, locally administered identifier.
VAD_POLL_MS, VAD_ON_POLLS = 100, 3


class VirtualXiao:
    def __init__(self, xmos, run_dir, log=print):
        self.xmos = xmos
        self.run_dir = run_dir
        self.log = log
        os.makedirs(os.path.join(run_dir, "dev", "serial", "by-id"), exist_ok=True)
        self.port_link = os.path.join(run_dir, "dev", "serial", "by-id",
                                      "usb-Reactor_prototype_XIAO_ReSpeaker_Audio_%s-if03" % MAC)
        self.audio_sock_path = os.path.join(run_dir, "xiao_audio.sock")
        self.lock = threading.Lock()
        self.audio_clients = []
        self.master = None
        self.alive = True
        self.boot_count = 0
        self.log_ring = []
        self.boot()
        threading.Thread(target=self._cdc_reader, daemon=True).start()
        threading.Thread(target=self._vad_task, daemon=True).start()
        threading.Thread(target=self._audio_server, daemon=True).start()

    # ---- boot / reset -------------------------------------------------------------
    def boot(self):
        self.boot_count += 1
        self.t0 = time.time()
        self.i2s_running = False
        self.probe_bclk_hz = self.xmos.bclk_hz()
        self.ext_clock_at_boot = self.probe_bclk_hz > 50000
        self.xmos_i2c = self.xmos.i2c_present()
        self.vad_enabled, self.vad_active, self.vad_speech = True, False, False
        self.vad_silence_ms, self.vad_doa = 30000, -1
        self.vad_polls = self.vad_errors = self.vad_wakes = self.vad_last_wake_ms = 0
        self.mic_host_mute = self.mic_cdc_mute = self.spk_host_mute = self.spk_cdc_mute = False
        self.mic_frames = self.mic_drops = self.spk_frames = self.spk_discarded = 0
        self.mounts = 1
        self.peek = None
        self.log_ring = []
        self._log("I (117) bridge: %s, reset reason %d" % (FW_VERSION, 1 if self.boot_count == 1 else 3))
        if self.ext_clock_at_boot:
            self._log("W (124) bridge: BCLK already clocked at %d Hz: another I2S master is on the bus "
                      "(XMOS on USB firmware?), I2S stays off; use i2s_on to override" % self.probe_bclk_hz)
        else:
            self.i2s_running = True
            self._log("I (142) bridge: i2s master running")
        self._log("I (143) bridge: usb started")
        self._log("I (426) bridge: xmos on i2c 0x2c: %s" % ("yes" if self.xmos_i2c else "no"))
        self._open_pty()

    def _log(self, line):
        self.log_ring.append(line)
        self.log_ring = self.log_ring[-40:]
        self.log("[xiao] " + line)

    def uptime_ms(self):
        return int((time.time() - self.t0) * 1000)

    def _open_pty(self):
        if self.master is not None:
            try: os.close(self.master)
            except OSError: pass
        m, s = pty.openpty()
        os.set_blocking(m, False)
        self.master, self.slave_path = m, os.ttyname(s)
        self._slave_keepalive = s        # keep the slave open so master writes never EIO
        try: os.unlink(self.port_link)
        except FileNotFoundError: pass
        os.symlink(self.slave_path, self.port_link)
        self.log("[xiao] CDC port at %s -> %s" % (self.port_link, self.slave_path))

    def _disappear(self, seconds, why):
        """USB re-enumeration: the port goes away and comes back."""
        self.log("[xiao] %s: port disappears for %.0f s" % (why, seconds))
        try: os.unlink(self.port_link)
        except FileNotFoundError: pass
        time.sleep(seconds)
        self.boot()

    # ---- CDC ----------------------------------------------------------------------
    def reply(self, text):
        with self.lock:
            try:
                os.write(self.master, text.encode())
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EIO):
                    raise

    def _cdc_reader(self):
        buf = b""
        while self.alive:
            try:
                chunk = os.read(self.master, 4096)
            except BlockingIOError:
                time.sleep(0.005); continue
            except OSError:
                time.sleep(0.05); continue
            if not chunk:
                time.sleep(0.01); continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.replace(b"\r", b"").decode(errors="replace")
                if len(line) > 127:
                    self.reply('{"error":"line too long"}\n')
                elif line:
                    self.command(line)

    def status_json(self):
        peek = self.xmos
        return json.dumps({
            "firmware": FW_VERSION, "rate": SR, "channels": 2, "uptime_ms": self.uptime_ms(),
            "usb": {"mounted": True, "suspended": False, "mounts": self.mounts, "cdc_connected": True},
            "speaker": {"streaming": False, "host_mute": self.spk_host_mute, "cdc_mute": self.spk_cdc_mute,
                        "volume_q8": -5888, "gain_q15": 2320, "fifo_avg": 0, "fifo_depth": 1024,
                        "underruns": 0, "frames": self.spk_frames, "discarded": self.spk_discarded, "i2s_errors": 0},
            "mic": {"streaming": bool(self.audio_clients), "host_mute": self.mic_host_mute, "cdc_mute": self.mic_cdc_mute,
                    "drops": self.mic_drops, "frames": self.mic_frames, "i2s_errors": 0},
            "i2s": {"running": self.i2s_running, "ext_clock_at_boot": self.ext_clock_at_boot, "probe_bclk_hz": self.probe_bclk_hz},
            "vad": {"enabled": self.vad_enabled, "active": self.vad_active, "speech": self.vad_speech, "doa": self.vad_doa,
                    "wakes": self.vad_wakes, "last_wake_ms": self.vad_last_wake_ms, "polls": self.vad_polls,
                    "errors": self.vad_errors, "silence_ms": self.vad_silence_ms},
            "xmos_i2c": self.xmos_i2c, "sim": True,
        }, separators=(",", ":")) + "\n"

    def command(self, line):
        if line == "ping": self.reply('{"ok":true,"reply":"pong"}\n')
        elif line == "status": self.reply(self.status_json())
        elif line == "log": self.reply("\n".join(self.log_ring) + '\n\n{"ok":true,"log_end":true}\n')
        elif line == "help":
            self.reply('{"commands":["ping","status","mic_mute 0|1","speaker_mute 0|1","i2s_on","i2s_off","i2s_peek",'
                       '"vad 0|1","vad_silence <ms>","log","i2c_txrx <hex> [nread]","i2c_read <hex header> <nread>",'
                       '"reboot","bootloader","help"],"sim":true}\n')
        elif line == "i2s_on":
            hz = self.xmos.bclk_hz(); ext = hz > 50000
            self.probe_bclk_hz = hz
            self.i2s_running = True
            self.reply('{"ok":true,"i2s_running":true,"external_clock_seen":%s,"probe_bclk_hz":%d}\n' % ("true" if ext else "false", hz))
        elif line == "i2s_off":
            self.i2s_running = False
            self.reply('{"ok":true,"i2s_running":false}\n')
        elif line == "i2s_peek":
            self.reply(self._peek_json())
        elif line in ("mic_mute 0", "mic_mute 1"):
            self.mic_cdc_mute = line[-1] == "1"; self.reply('{"ok":true}\n')
        elif line in ("speaker_mute 0", "speaker_mute 1"):
            self.spk_cdc_mute = line[-1] == "1"; self.reply('{"ok":true}\n')
        elif line in ("vad 0", "vad 1"):
            self.vad_enabled = line[-1] == "1"
            if not self.vad_enabled: self.vad_active = False
            self.reply('{"ok":true}\n')
        elif line.startswith("vad_silence "):
            try: ms = int(line[12:])
            except ValueError: ms = -1
            if 1000 <= ms <= 600000: self.vad_silence_ms = ms; self.reply('{"ok":true}\n')
            else: self.reply('{"error":"vad_silence 1000..600000 ms"}\n')
        elif line.startswith("i2c_txrx "): self.reply(self._i2c_txrx(line[9:]))
        elif line.startswith("i2c_read "): self.reply(self._i2c_read(line[9:]))
        elif line == "reboot":
            self.reply('{"ok":true,"action":"reboot"}\n')
            threading.Thread(target=self._disappear, args=(2.0, "reboot"), daemon=True).start()
        elif line == "bootloader":
            self.reply('{"ok":true,"action":"bootloader","hint":"esptool over USB-Serial-JTAG; BOOT+RESET if this fails"}\n')
            threading.Thread(target=self._disappear, args=(8.0, "bootloader (sim: comes back by itself after 8 s)"), daemon=True).start()
        else:
            self.reply('{"error":"unknown command; try help"}\n')

    @staticmethod
    def _parse_hex(args):
        parts = args.split()
        if not parts: return None, None
        try: tx = bytes.fromhex(parts[0])
        except ValueError: return None, None
        nrx = int(parts[1]) if len(parts) > 1 else 0
        if not tx or nrx < 0 or nrx > 64: return None, None
        return tx, nrx

    def _i2c_txrx(self, args):
        if not self.xmos_i2c: return '{"error":"xmos not present on i2c"}\n'
        tx, nrx = self._parse_hex(args)
        if tx is None: return '{"error":"usage: i2c_txrx <hex> [nread<=64]"}\n'
        if nrx == 0:
            if len(tx) >= 3 and len(tx) == 3 + tx[2]:
                self.xmos.write(tx[0], tx[1], tx[3:])          # status of a write is not read back here
            return '{"ok":true,"rx":""}\n'
        # combined write+read: the real board answers RETRY plus an echo of the header
        return '{"ok":true,"rx":"%s"}\n' % (bytes([64]) + tx[1:] + b"\0" * 64)[:nrx].hex()

    def _i2c_read(self, args):
        if not self.xmos_i2c: return '{"error":"xmos not present on i2c"}\n'
        tx, nrx = self._parse_hex(args)
        if tx is None or nrx < 1 or len(tx) < 3: return '{"error":"usage: i2c_read <hex header> <nread 1..64>"}\n'
        resid, cmd, ln = tx[0], tx[1] & 0x7F, tx[2] - 1
        tries = 0
        while tries < 50:
            tries += 1
            st, payload = self.xmos.read(resid, cmd, ln)
            if st != 64: break
        rx = (bytes([st]) + payload)[:nrx]
        return '{"ok":%s,"status":%d,"tries":%d,"rx":"%s"}\n' % ("true" if st == 0 else "false", st, tries, rx.hex())

    def _peek_json(self):
        if self.peek is None: return '{"error":"no I2S data yet"}\n'
        L, R = self.peek
        def stat(ch):
            rms = float(np.sqrt(np.mean(ch.astype(np.float64) ** 2)))
            return '{"min":%d,"max":%d,"or":"0x%08x","rms32":%.0f,"rms_dbfs":%.1f}' % (
                int(ch.min()), int(ch.max()), int(np.bitwise_or.reduce(ch.view(np.uint32))) if len(ch) else 0, rms,
                20 * np.log10(rms / 2147483648.0) if rms > 0 else -999.0)
        words = ",".join('"0x%08x"' % (int(v) & 0xFFFFFFFF) for v in np.column_stack([L[:8], R[:8]]).ravel())
        return '{"frames":%d,"i2s_running":%s,"L":%s,"R":%s,"words":[%s]}\n' % (
            len(L), "true" if self.i2s_running else "false", stat(L), stat(R), words)

    # ---- VAD poller (mirrors vad_task) ----------------------------------------------
    def _vad_task(self):
        speech_run, last_speech = 0, 0.0
        while self.alive:
            time.sleep(VAD_POLL_MS / 1000.0)
            if not self.xmos_i2c or not self.vad_enabled: continue
            st, payload = 64, b""
            for _ in range(20):
                st, payload = self.xmos.read(20, 18, 4)
                if st != 64: break
                time.sleep(0.002)
            self.vad_polls += 1
            if st != 0: self.vad_errors += 1; continue
            doa, speech = struct.unpack("<HH", payload)
            self.vad_speech = bool(speech)
            if speech: self.vad_doa = doa
            now = time.time()
            if speech:
                last_speech = now
                speech_run += 1
                if speech_run >= VAD_ON_POLLS and not self.vad_active:
                    self.vad_active = True
                    self.vad_wakes += 1
                    self.vad_last_wake_ms = self.uptime_ms()
                    self.reply('{"event":"wake","doa":%d,"uptime_ms":%d}\n' % (doa, self.uptime_ms()))
            else:
                speech_run = 0
                if self.vad_active and now - last_speech > self.vad_silence_ms / 1000.0:
                    self.vad_active = False
                    self.reply('{"event":"silence","uptime_ms":%d}\n' % self.uptime_ms())

    # ---- audio path -------------------------------------------------------------------
    def on_i2s_block(self, L, R):
        """Called every 10 ms with the XMOS I2S words; forwards S16 stereo to audio clients."""
        if not self.i2s_running:
            L = np.zeros_like(L); R = np.zeros_like(R)
        else:
            self.peek = (L, R)
            self.mic_frames += len(L)
        if self.mic_host_mute or self.mic_cdc_mute:
            L = np.zeros_like(L); R = np.zeros_like(R)
        pcm = np.column_stack([L >> 16, R >> 16]).astype("<i2").tobytes()
        dead = []
        for c in self.audio_clients:
            try:
                c.sendall(pcm)
            except (BlockingIOError, InterruptedError):
                self.mic_drops += 1
            except OSError:
                dead.append(c)
        for c in dead:
            self.audio_clients.remove(c)
            try: c.close()
            except OSError: pass

    def _audio_server(self):
        try: os.unlink(self.audio_sock_path)
        except FileNotFoundError: pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.audio_sock_path); srv.listen(4)
        self.log("[xiao] audio (USB IN stand-in) at %s" % self.audio_sock_path)
        while self.alive:
            c, _ = srv.accept()
            c.setblocking(False)
            self.audio_clients.append(c)
