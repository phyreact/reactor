import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "zero"))
from box_peripherals import Fan, Tachometer, ToF
import box_host as host


class PeripheralsTests(unittest.TestCase):
    def test_no_unqualified_io(self):
        with tempfile.TemporaryDirectory() as directory:
            fan = Fan(directory)
            fan.start()
            with self.assertRaises(RuntimeError):
                fan.set(50)
            self.assertEqual(list(Path(directory).iterdir()), [])
        tof = ToF({"carrier_3v3_qualified": False})
        with self.assertRaises(RuntimeError):
            tof.start()
        self.assertIsNone(tof.lib)

    def test_tof_must_share_bus_supply(self):
        tof = ToF({"carrier_3v3_qualified": True, "supply_policy": "relay"})
        with self.assertRaises(RuntimeError):
            tof.start()

    def test_tof_failure_stops_without_raising_zero_distance(self):
        tof = ToF({})
        tof.lib = Mock()
        tof.lib.box_tof_read.return_value = -255
        tof.running = True
        tof.poll()
        self.assertFalse(tof.running)
        self.assertIsNone(tof.sample)
        self.assertIn("-255", tof.error)
        tof.lib.box_tof_stop.assert_called_once()

    def test_tof_command_never_switches_legacy_relay(self):
        link, fan, tof = Mock(), Mock(), Mock()
        link.wait_status.return_value = {"host_on": True, "shutdown": 0}
        host.request_command(link, fan, {"command": "tof-on"}, tof)
        tof.start.assert_called_once()
        link.command.assert_not_called()
        link.wait_status.return_value["shutdown"] = 2
        with self.assertRaises(RuntimeError):
            host.request_command(link, fan, {"command": "tof-on"}, tof)
        host.request_command(link, fan, {"command": "tof-off"}, tof)
        tof.stop.assert_called_once()

    def test_full_speed_start_and_stall(self):
        now = [0.0]
        with tempfile.TemporaryDirectory() as directory:
            fan = Fan(directory, {"electrical_qualified": True}, lambda: now[0])
            fan.set(35)
            self.assertEqual(fan.applied, 100)
            now[0] = 0.99
            fan.poll()
            self.assertEqual(fan.applied, 100)
            now[0] = 1
            fan.poll()
            self.assertEqual(fan.applied, 35)
            fan.lines = Mock()
            fan.lines.wait_edge_events.return_value = False
            now[0] = 2.1
            fan.poll()
            self.assertEqual(fan.applied, 100)
            self.assertEqual(fan.fault, "FG_NOT_SEEN_OR_LOST")
            fan.set(25)
            self.assertEqual(fan.applied, 100)
            fan.close()
            fan.lines.release.assert_called_once()

    def test_nonfinite_pwm_rejected(self):
        fan = Fan(None)
        for value in (float("nan"), float("inf"), -1, 101):
            with self.assertRaises(ValueError):
                fan.set(value)

    def test_tach_no_assumed_pulses_per_revolution(self):
        now = [0.0]
        tach = Tachometer(clock=lambda: now[0])
        tach.edge(1_000_000, 1)
        tach.edge(11_000_000, 2)
        self.assertEqual(tach.status()["pulse_hz"], 100)
        self.assertIsNone(tach.status()["rpm"])
        now[0] = 3
        self.assertTrue(tach.status()["stale"])
        self.assertIsNone(tach.status()["pulse_hz"])

    def test_tach_loss_not_reported_as_valid_rpm(self):
        tach = Tachometer(2)
        tach.edge(1_000_000, 1)
        tach.edge(11_000_000, 2)
        self.assertEqual(tach.status()["rpm"], 3000)
        tach.edge(21_000_000, 4)
        self.assertTrue(tach.status()["lost_events"])
        self.assertIsNone(tach.status()["rpm"])

    def test_tof_error_does_not_prevent_orderly_shutdown(self):
        link, tof = Mock(), Mock()
        link.command.return_value = {"shutdown": 2}
        tof.stop.side_effect = RuntimeError("I2C transfer failed")
        result = host.request_command(link, None, {"command": "all-off"}, tof)
        link.command.assert_called_once_with(host.ALL_OFF, 0)
        self.assertEqual(result["tof_stop_error"], "I2C transfer failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
