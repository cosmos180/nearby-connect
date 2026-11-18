import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from core import Presence, decode_hint, on_local_network


def lan(address="192.0.2.46", prefix=24, flags=None, name="wlp0s20f3"):
    return [{"ifname": name, "flags": flags or ["UP", "LOWER_UP"],
             "addr_info": [{"family": "inet", "local": address, "prefixlen": prefix, "scope": "global"}]}]


class ProtocolTest(unittest.TestCase):
    def test_network_order_and_no_wifi(self):
        self.assertEqual(decode_hint([1, 192, 0, 2, 84]), "192.0.2.84")
        self.assertIsNone(decode_hint([1, 0, 0, 0, 0]))

    def test_malformed_or_non_unicast_payload_is_rejected(self):
        for value in ([1], [2, 192, 0, 2, 84], [1, 127, 0, 0, 1], [1, 224, 1, 1, 1], [1, 169, 254, 1, 1]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_hint(value)

    def test_ip_must_be_other_host_in_current_lan(self):
        self.assertTrue(on_local_network("192.0.2.84", lan()))
        for address in (None, "192.168.2.1", "192.0.2.46", "192.0.2.0", "192.0.2.255"):
            self.assertFalse(on_local_network(address, lan()))

    def test_virtual_and_down_interfaces_do_not_authorize_targets(self):
        for name in ("docker0", "br-123", "virbr0", "tun0", "vethabc"):
            self.assertFalse(on_local_network("192.0.2.84", lan(name=name)))
        self.assertFalse(on_local_network("192.0.2.84", lan(flags=["UP"])))
        self.assertFalse(on_local_network("192.0.2.84", lan(flags=["UP", "LOWER_UP", "POINTOPOINT"])))


class ProximityTest(unittest.TestCase):
    def near(self):
        state = Presence()
        state.observe(100, -50, "192.0.2.84")
        state.observe(101, -50, "192.0.2.84")
        return state

    def test_two_separate_samples_required(self):
        state = Presence()
        self.assertFalse(state.observe(100, -50, "192.0.2.84"))
        self.assertFalse(state.observe(100.1, -50, "192.0.2.84"))
        self.assertFalse(state.near)
        self.assertTrue(state.observe(101, -50, "192.0.2.84"))

    def test_far_phone_never_triggers(self):
        state = Presence()
        for now in range(100):
            state.observe(now, -90, "192.0.2.84")
        self.assertFalse(state.due(100, True, False))

    def test_signal_hysteresis_and_delayed_departure(self):
        state = self.near()
        state.observe(102, -79, state.ip)
        state.observe(103, -79, state.ip)
        self.assertTrue(state.near)
        self.assertFalse(state.expire(125))
        self.assertTrue(state.expire(140))
        self.assertFalse(state.near)
        self.assertIsNone(state.ip)

    def test_live_but_weak_signal_expires(self):
        state = self.near()
        for now in range(102, 150):
            state.observe(now, -100, "192.0.2.84")
        self.assertFalse(state.near)

    def test_distant_encounters_cannot_combine_samples(self):
        state = Presence()
        state.observe(100, -50, "192.0.2.84")
        state.observe(120, -50, "192.0.2.84")
        self.assertFalse(state.near)

    def test_no_retries_for_connected_or_unpaired_devices(self):
        state = self.near()
        self.assertFalse(state.due(102, False, False))
        self.assertFalse(state.due(102, True, True))
        self.assertTrue(state.due(102, True, False))

    def test_retry_backoff_and_ip_change(self):
        state = self.near()
        for now, delay in ((102, 5), (107, 10), (117, 15), (132, 15), (147, 15)):
            state.attempted(now)
            self.assertEqual(state.next_attempt, now + delay)
            self.assertFalse(state.due(now + delay - 1, True, False))
        state.observe(213, -50, "192.0.2.85")
        state.observe(214, -50, "192.0.2.85")
        self.assertTrue(state.due(214, True, False))
        self.assertEqual(state.ip, "192.0.2.85")

    def test_invalid_rssi_is_ignored(self):
        state = Presence()
        for now, value in enumerate((-128, 127, 300)):
            state.observe(now, value, "192.0.2.84")
        self.assertIsNone(state.rssi)
        self.assertFalse(state.near)

    def test_return_after_absence_needs_new_samples(self):
        state = self.near()
        self.assertFalse(state.observe(200, -50, "192.0.2.84"))
        self.assertFalse(state.near)
        self.assertTrue(state.observe(201, -50, "192.0.2.84"))


if __name__ == "__main__":
    unittest.main()
