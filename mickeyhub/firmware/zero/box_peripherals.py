"""VL53L8CX software sleep and qualified fan control on the target ZERO."""
import ctypes
from datetime import timedelta
import math
from pathlib import Path
import time


class ToF:
    def __init__(self, config):
        self.config = config or {}
        self.lib = None
        self.running = False
        self.sample = None
        self.error = None

    def _check(self, result):
        if result:
            self.error = f"VL53L8CX driver status {result}"
            raise RuntimeError(self.error)

    def start(self):
        if self.config.get("carrier_3v3_qualified") is not True:
            raise RuntimeError("ToF carrier VIN and 3.3V I/O compatibility are not qualified")
        if self.config.get("supply_policy") != "same_3v3_as_i2c":
            raise RuntimeError("ToF must share J37 3.3V; M17 power cycling is disabled")
        if not self.lib:
            device = self.config.get("i2c_device")
            if not device:
                raise RuntimeError("Map I2C4_M0 with preflight before enabling ToF")
            lib = ctypes.CDLL(self.config["library"])
            lib.box_tof_open.argtypes = [ctypes.c_char_p]
            lib.box_tof_read.argtypes = [
                ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_uint8),
                ctypes.POINTER(ctypes.c_uint8)]
            for name in ("open", "start", "stop", "close", "read"):
                getattr(lib, f"box_tof_{name}").restype = ctypes.c_int
            self._check(lib.box_tof_open(device.encode()))
            self.lib = lib
        self._check(self.lib.box_tof_start())
        self.running = True
        self.error = None
        return self.status()

    def stop(self):
        if self.lib:
            self._check(self.lib.box_tof_stop())
        self.running = False
        return self.status()

    def poll(self):
        if not self.running:
            return
        distances = (ctypes.c_int16 * 64)()
        statuses, targets = (ctypes.c_uint8 * 64)(), (ctypes.c_uint8 * 64)()
        result = self.lib.box_tof_read(distances, statuses, targets)
        if result < 0:
            self.error = f"VL53L8CX read failed: {result}"
            self.running = False
            # Attempt to stop, retaining the original error. Never toggle M17
            # underneath host pullups when the bus stops responding.
            self.lib.box_tof_stop()
        elif result == 1:
            self.sample = {"distance_mm": list(distances), "target_status": list(statuses),
                           "targets": list(targets), "resolution": [8, 8],
                           "received_at_monotonic": time.monotonic()}

    def close(self):
        if self.lib:
            result = self.lib.box_tof_close()
            self.lib = None
            self.running = False
            self._check(result)

    def status(self):
        return {"running": self.running, "error": self.error, "sample": self.sample,
                "supply_policy": "same_3v3_as_i2c", "relay_power_control": False}


class Tachometer:
    """Rising-edge counts. Unknown pulses/revolution -> Hz only, never invented RPM."""
    def __init__(self, pulses_per_revolution=None, clock=time.monotonic):
        if pulses_per_revolution is not None and (
                not isinstance(pulses_per_revolution, int) or
                isinstance(pulses_per_revolution, bool) or pulses_per_revolution <= 0):
            raise ValueError("pulses_per_revolution must be a measured positive integer or null")
        self.ppr, self.clock = pulses_per_revolution, clock
        self.last_timestamp = None
        self.last_received = None
        self.hz = None
        self.lost_events = False
        self.sequence = None

    def edge(self, timestamp_ns, sequence=None):
        if self.sequence is not None and sequence is not None and sequence != self.sequence + 1:
            self.lost_events = True
        self.sequence = sequence
        if self.last_timestamp is not None:
            interval = timestamp_ns - self.last_timestamp
            if interval <= 0:
                raise ValueError("FG timestamps must increase")
            self.hz = 1e9 / interval
        self.last_timestamp = timestamp_ns
        self.last_received = self.clock()

    def status(self):
        stale = self.last_received is None or self.clock() - self.last_received > 2
        hz = None if stale or self.lost_events else self.hz
        return {"pulse_hz": hz, "rpm": hz * 60 / self.ppr if hz is not None and self.ppr else None,
                "pulses_per_revolution": self.ppr, "stale": stale, "lost_events": self.lost_events}


class Fan:
    def __init__(self, channel, config=None, clock=time.monotonic):
        self.config = config or {}
        self.channel = Path(channel) if channel else None
        self.clock = clock
        self.requested = self.applied = 100
        self.started_at = None
        self.kick_until = 0
        self.fault = None
        self.tach = Tachometer(self.config.get("pulses_per_revolution"), clock)
        self.lines = None
        self.offset = 1  # ZERO header 11 = GPIO3_A1, local gpio3 offset 1
        frequency = self.config.get("pwm_frequency_hz", 25000)
        if not isinstance(frequency, int) or not 100 <= frequency <= 100000:
            raise ValueError("PWM frequency must be an integer in 100..100000Hz")
        self.period = round(1e9 / frequency)

    def _write(self, duty):
        if self.config.get("electrical_qualified") is not True:
            raise RuntimeError("B3 pinout, PWM levels and FG levels must be qualified first")
        if not self.channel:
            raise RuntimeError("PWM14_M0 sysfs channel has not been configured")
        p = self.channel
        # Disable before changing period; M42 PHASE low is the full-speed request.
        (p / "enable").write_text("0")
        (p / "duty_cycle").write_text("0")
        (p / "period").write_text(str(self.period))
        (p / "polarity").write_text("normal")
        (p / "duty_cycle").write_text(str(round(self.period * (100 - duty) / 100)))
        (p / "enable").write_text("1")
        self.applied = duty

    def set(self, duty):
        if not math.isfinite(duty) or not 0 <= duty <= 100:
            raise ValueError("Fan duty must be finite and in 0..100")
        # A zero PWM request is not a promise that this fan can stop.
        self._write(100 if self.fault or
                    (duty > 0 and (self.started_at is None or self.requested == 0)) else duty)
        if duty > 0 and (self.started_at is None or self.requested == 0):
            self.started_at = self.clock()
            self.kick_until = self.started_at + 1
        self.requested = duty

    def start(self):
        if self.config.get("electrical_qualified") is not True:
            return
        self.set(100)
        chip = self.config.get("tach_gpiochip")
        if chip:
            import gpiod
            self.lines = gpiod.request_lines(chip, consumer="box-fan-fg", config={
                self.offset: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT,
                                               bias=gpiod.line.Bias.DISABLED,
                                               edge_detection=gpiod.line.Edge.RISING)})

    def poll(self):
        if self.lines and self.lines.wait_edge_events(timedelta(0)):
            for event in self.lines.read_edge_events():
                self.tach.edge(event.timestamp_ns, event.line_seqno)
        now = self.clock()
        if self.lines and self.requested > 0 and self.started_at is not None and now - self.started_at > 2:
            status = self.tach.status()
            if status["stale"] or status["lost_events"]:
                self.fault = "FG_NOT_SEEN_OR_LOST"
                if self.applied != 100:
                    self._write(100)
        if not self.fault and self.applied != self.requested and now >= self.kick_until:
            self._write(self.requested)

    def status(self):
        return {"requested_percent": self.requested, "applied_percent": self.applied,
                "electrical_qualified": self.config.get("electrical_qualified") is True,
                "fault": self.fault, "tach": self.tach.status()}

    def close(self):
        if self.config.get("electrical_qualified") is True and self.channel:
            self._write(100)
        if self.lines:
            self.lines.release()
