from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from gi.repository import GLib
from core import Presence
from nearby_connect import Watcher, APP, ROOT

UUID = "00000000-0000-4000-8000-000000000001"
ADAPTER = "/org/bluez/hci0"
PATH = ADAPTER + "/dev_11_22_33_44_55_66"


class RadioEventTest(unittest.TestCase):
    def setUp(self):
        self.watcher = Watcher.__new__(Watcher)
        self.watcher.config = {"service_uuid": UUID}
        self.watcher.presence = Presence()
        self.watcher.adapter = ADAPTER
        self.watcher.own_scan = True
        self.watcher.devices = {}

    def event(self, changed, now, path=PATH):
        params = GLib.Variant("(sa{sv}as)", ("org.bluez.Device1", changed, []))
        with patch("nearby_connect.time.monotonic", return_value=now):
            self.watcher.properties_changed(None, None, path, None, None, params)

    def hint(self):
        return {"RSSI": GLib.Variant("n", -50),
                "ServiceData": GLib.Variant("a{sv}", {UUID: GLib.Variant("ay", [1, 192, 0, 2, 84])})}

    def test_fresh_packet_then_new_random_address_is_same_phone(self):
        self.event(self.hint(), 100)
        self.event(self.hint(), 101, path=ADAPTER + "/dev_AA_BB_CC_DD_EE_FF")
        self.assertTrue(self.watcher.presence.near)
        self.assertEqual(self.watcher.presence.ip, "192.0.2.84")

    def test_cached_service_data_plus_rssi_is_not_fresh_presence(self):
        self.event(self.hint(), 100)
        self.event({"RSSI": GLib.Variant("n", -45)}, 101)
        self.assertFalse(self.watcher.presence.near)
        self.assertEqual(self.watcher.presence.last_seen, 100)

    def test_other_devices_and_malformed_payload_cannot_trigger(self):
        wrong = self.hint()
        wrong["ServiceData"] = GLib.Variant("a{sv}", {"0000180f-0000-1000-8000-00805f9b34fb": GLib.Variant("ay", [1])})
        self.event(wrong, 100)
        bad = self.hint()
        bad["ServiceData"] = GLib.Variant("a{sv}", {UUID: GLib.Variant("ay", [99])})
        self.event(bad, 101)
        self.assertIsNone(self.watcher.presence.rssi)

    def test_no_presence_from_other_adapter_or_when_not_scanning(self):
        self.event(self.hint(), 100, path="/org/bluez/hci1/dev_11_22_33_44_55_66")
        self.watcher.own_scan = False
        self.event(self.hint(), 101)
        self.assertIsNone(self.watcher.presence.rssi)


class ReconnectGateTest(unittest.TestCase):
    def setUp(self):
        self.watcher = Watcher.__new__(Watcher)
        w = self.watcher
        w.config = {"device_id": "phone"}
        w.presence = Presence()
        w.presence.observe(100, -50, "192.0.2.84")
        w.presence.observe(101, -50, "192.0.2.84")
        w.gs = {"Paired": True, "Connected": False}
        w.adapter = ADAPTER
        w.own_scan = True
        w.scan_deadline = 200
        w.scan_next = 200
        w.last_snapshot = 100
        w.last_status = None
        w.last_error = None
        w.interfaces = [{"ifname": "wlan0", "flags": ["LOWER_UP"], "addr_info": [
            {"family": "inet", "scope": "global", "local": "192.0.2.46", "prefixlen": 24}]}]
        w.stop_scan = Mock()
        w.check_gs = Mock()
        w.check_network = Mock()
        w.write_status = Mock()
        w.reconnect = Mock()

    def tick(self):
        with patch("nearby_connect.time.monotonic", return_value=102):
            self.watcher.tick()

    def test_connection_events_stop_then_immediately_restart_discovery(self):
        w = self.watcher
        w.start_scan = Mock()
        def event(value):
            params = GLib.Variant("(sa{sv}as)", ("device", {"Connected": GLib.Variant("b", value)}, []))
            with patch("nearby_connect.time.monotonic", return_value=102):
                w.gs_changed(None, None, None, None, None, params)
        event(True)
        w.stop_scan.assert_called_once()
        self.assertFalse(w.presence.near)
        w.own_scan = False
        event(False)
        w.start_scan.assert_called_once_with(102)

    def test_valid_phone_requests_reconnect_only_once_during_cooldown(self):
        self.tick()
        self.tick()
        self.watcher.reconnect.assert_called_once()

    def test_unpaired_connected_far_or_other_lan_never_reconnect(self):
        for condition, expected in (("unpaired", "target_not_paired"), ("connected", "connected"),
                                    ("far", "waiting_for_phone"), ("other_lan", "waiting_for_same_lan"),
                                    ("no_wifi", "waiting_for_phone_wifi")):
            with self.subTest(condition=condition):
                self.setUp()
                if condition == "unpaired": self.watcher.gs["Paired"] = False
                if condition == "connected": self.watcher.gs["Connected"] = True
                if condition == "far": self.watcher.presence.reset()
                if condition == "other_lan": self.watcher.presence.ip = "10.1.2.3"
                if condition == "no_wifi": self.watcher.presence.ip = None
                self.tick()
                self.watcher.reconnect.assert_not_called()
                self.assertEqual(self.watcher.reason, expected)

    def test_real_gvariant_wire_shape_only_invokes_discovery_actions(self):
        self.watcher.session = object()
        self.watcher.dry_run = False
        with patch("nearby_connect.call") as remote:
            Watcher.reconnect(self.watcher)
        actions = [entry.args[5].unpack() for entry in remote.call_args_list]
        self.assertEqual(actions, [("connect", ["lan://192.0.2.84:1716"], {})])
        for entry in remote.call_args_list:
            self.assertEqual(entry.args[1:5], (APP, ROOT, "org.gtk.Actions", "Activate"))


if __name__ == "__main__":
    unittest.main()
