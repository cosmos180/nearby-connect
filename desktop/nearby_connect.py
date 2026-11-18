#!/usr/bin/python3
"""BlueZ proximity watcher for an already paired GSConnect phone."""

import argparse
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib
try:
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix
    add_signal = GLibUnix.signal_add
except (ImportError, ValueError):
    add_signal = GLib.unix_signal_add

from core import Presence, decode_hint, on_local_network

APP = "org.gnome.Shell.Extensions.GSConnect"
ROOT = "/org/gnome/Shell/Extensions/GSConnect"
DEVICE = APP + ".Device"
LOG = logging.getLogger("nearby-connect")
CONFIG = Path.home() / ".config/nearby-connect/config.json"
STATE = Path.home() / ".local/state/nearby-connect/status.json"


def call(bus, dest, path, interface, method, args=None):
    return bus.call_sync(dest, path, interface, method, args, None,
                         Gio.DBusCallFlags.NONE, 3000, None).unpack()


def load_config(path):
    config = json.loads(Path(path).read_text())
    config["service_uuid"] = str(uuid.UUID(config["service_uuid"]))
    device_id = config["device_id"]
    if not device_id or not all(c.isalnum() or c == "_" for c in device_id):
        raise ValueError("Invalid GSConnect device ID")
    enter = config.get("enter_rssi", -72)
    exit_ = config.get("exit_rssi", -82)
    if not -120 <= exit_ < enter <= -20:
        raise ValueError("Expected -120 <= exit_rssi < enter_rssi <= -20")
    return config


class Watcher:
    def __init__(self, config, dry_run=False):
        self.config = config
        self.dry_run = dry_run
        self.presence = Presence(enter_rssi=config.get("enter_rssi", -72),
                                 exit_rssi=config.get("exit_rssi", -82))
        self.system = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.loop = GLib.MainLoop()
        self.adapter = None
        self.own_scan = False
        self.scan_deadline = 0
        self.scan_next = 0
        self.devices = {}
        self.interfaces = []
        self.network_checked = float("-inf")
        self.gs = {}
        self.gs_checked = float("-inf")
        self.reason = "waiting_for_phone"
        self.last_error = None
        self.last_status = None
        self.saved_state = None
        self.saved_at = 0
        self.last_snapshot = 0
        self.system.signal_subscribe("org.bluez", "org.freedesktop.DBus.Properties",
                                     "PropertiesChanged", None, None,
                                     Gio.DBusSignalFlags.NONE, self.properties_changed)
        self.system.signal_subscribe("org.bluez", "org.freedesktop.DBus.ObjectManager",
                                     "InterfacesAdded", None, None,
                                     Gio.DBusSignalFlags.NONE, self.interfaces_added)
        self.system.signal_subscribe("org.bluez", "org.freedesktop.DBus.ObjectManager",
                                     "InterfacesRemoved", None, None,
                                     Gio.DBusSignalFlags.NONE, self.interfaces_removed)
        self.system.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus",
                                     "NameOwnerChanged", "/org/freedesktop/DBus", "org.bluez",
                                     Gio.DBusSignalFlags.NONE, self.bluez_restarted)
        self.session.signal_subscribe(APP, "org.freedesktop.DBus.Properties",
                                      "PropertiesChanged", ROOT + "/Device/" + config["device_id"], DEVICE,
                                      Gio.DBusSignalFlags.NONE, self.gs_changed)
        for member in ("InterfacesAdded", "InterfacesRemoved"):
            self.session.signal_subscribe(APP, "org.freedesktop.DBus.ObjectManager", member,
                                          ROOT, None, Gio.DBusSignalFlags.NONE, self.gs_lifecycle)
        self.session.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus",
                                      "NameOwnerChanged", None, APP, Gio.DBusSignalFlags.NONE,
                                      self.gs_lifecycle)
        # After resume, all radio observations must be collected again.
        self.system.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager",
                                     "PrepareForSleep", None, None,
                                     Gio.DBusSignalFlags.NONE, self.sleep_changed)

    def refresh_objects(self):
        objects = call(self.system, "org.bluez", "/", "org.freedesktop.DBus.ObjectManager",
                       "GetManagedObjects")[0]
        powered = [path for path, ifaces in objects.items()
                   if ifaces.get("org.bluez.Adapter1", {}).get("Powered", False)]
        requested = self.config.get("adapter")
        adapter = requested if requested in powered else (powered[0] if powered and not requested else None)
        if adapter != self.adapter:
            self.stop_scan()
            self.presence.reset()
            self.adapter = adapter
            self.scan_next = 0
        self.devices = {p: i["org.bluez.Device1"] for p, i in objects.items() if "org.bluez.Device1" in i}
        # These are cached BlueZ properties, NOT evidence of a nearby phone.

    def start_scan(self, now):
        filters = {"Transport": GLib.Variant("s", "le"),
                   "UUIDs": GLib.Variant("as", [self.config["service_uuid"]]),
                   "DuplicateData": GLib.Variant("b", True)}
        call(self.system, "org.bluez", self.adapter, "org.bluez.Adapter1",
             "SetDiscoveryFilter", GLib.Variant("(a{sv})", (filters,)))
        call(self.system, "org.bluez", self.adapter, "org.bluez.Adapter1", "StartDiscovery")
        self.own_scan = True
        self.scan_deadline = now + 8
        self.scan_next = now + 12

    def stop_scan(self):
        if self.own_scan and self.adapter:
            try:
                call(self.system, "org.bluez", self.adapter, "org.bluez.Adapter1", "StopDiscovery")
            except GLib.Error:
                pass
        self.own_scan = False

    def bluez_restarted(self, *args):
        self.own_scan = False
        self.adapter = None
        self.devices.clear()
        self.presence.reset()
        self.last_snapshot = 0

    def sleep_changed(self, connection, sender, path, interface, member, params):
        if params.unpack()[0]:
            self.stop_scan()
        self.presence.reset()
        self.scan_next = 0
        self.last_snapshot = 0

    def gs_changed(self, connection, sender, path, interface, member, params):
        _, changed, invalid = params.unpack()
        keys = {"Connected", "Paired"}
        if keys.intersection(invalid):
            self.gs_checked = float("-inf")
        elif keys.intersection(changed):
            self.gs.update(changed)
        else:
            return
        self.tick()

    def gs_lifecycle(self, *args):
        self.gs_checked = float("-inf")
        self.tick()

    def interfaces_added(self, connection, sender, path, interface, member, params):
        obj, ifaces = params.unpack()
        if "org.bluez.Adapter1" in ifaces:
            self.last_snapshot = 0
        if "org.bluez.Device1" in ifaces:
            self.devices[obj] = ifaces["org.bluez.Device1"]
            self.observe(obj, self.devices[obj])

    def interfaces_removed(self, connection, sender, path, interface, member, params):
        obj, ifaces = params.unpack()
        self.devices.pop(obj, None)
        if obj == self.adapter:
            self.adapter = None
            self.own_scan = False
            self.presence.reset()
            self.last_snapshot = 0

    def properties_changed(self, connection, sender, path, interface, member, params):
        iface, changed, invalid = params.unpack()
        if iface == "org.bluez.Adapter1":
            if "Powered" in changed:
                if path == self.adapter and not changed["Powered"]:
                    self.stop_scan()
                    self.adapter = None
                    self.presence.reset()
                self.last_snapshot = 0
            if path == self.adapter and changed.get("Discovering") is False:
                self.own_scan = False
            return
        if iface != "org.bluez.Device1":
            return
        cached = self.devices.setdefault(path, {})
        cached.update(changed)
        for key in invalid:
            cached.pop(key, None)
        # BlueZ can retain ServiceData after advertising stops. An RSSI change
        # alone must never turn a cached UUID into proof of current presence.
        if self.config["service_uuid"] in changed.get("ServiceData", {}):
            self.observe(path, cached)

    def observe(self, path, props):
        if not self.own_scan or not path.startswith(self.adapter + "/"):
            return
        payload = props.get("ServiceData", {}).get(self.config["service_uuid"])
        rssi = props.get("RSSI")
        if payload is None or rssi is None:
            return
        try:
            address = decode_hint(payload)
        except (ValueError, TypeError):
            return
        if self.presence.observe(time.monotonic(), rssi, address):
            LOG.info("Phone nearby (RSSI %.0f dBm)", self.presence.rssi)

    def check_gs(self, now):
        if now - self.gs_checked < 120:
            return
        objects = call(self.session, APP, ROOT, "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")[0]
        self.gs = objects.get(ROOT + "/Device/" + self.config["device_id"], {}).get(DEVICE, {})
        self.gs_checked = now

    def check_network(self, now):
        if now - self.network_checked < 3:
            return
        result = subprocess.run(["ip", "-j", "-4", "address", "show", "up"],
                                capture_output=True, text=True, timeout=3, check=True)
        self.interfaces = json.loads(result.stdout)
        self.network_checked = now

    def reconnect(self):
        target = "lan://" + self.presence.ip + ":1716"
        LOG.info("Requesting GSConnect discovery at %s%s", target, " (dry-run)" if self.dry_run else "")
        if self.dry_run:
            return
        call(self.session, APP, ROOT, "org.gtk.Actions", "Activate",
             GLib.Variant("(sava{sv})", ("connect", [GLib.Variant("s", target)], {})))

    def status(self):
        seen = time.monotonic() - self.presence.last_seen
        return {"phone": self.config.get("name", self.config["device_id"]),
                "nearby": self.presence.near,
                "rssi_dbm": round(self.presence.rssi, 1) if self.presence.rssi is not None else None,
                "last_seen_seconds": round(seen, 1) if seen != float("inf") else None,
                "phone_ipv4": self.presence.ip,
                "gsconnect_paired": self.gs.get("Paired", False),
                "gsconnect_connected": self.gs.get("Connected", False),
                "bluetooth_adapter": self.adapter, "scanning": self.own_scan,
                "state": self.reason, "error": self.last_error,
                "dry_run": self.dry_run, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    def tick(self):
        now = time.monotonic()
        try:
            if now - self.last_snapshot >= 15:
                self.refresh_objects()
                self.last_snapshot = now
            self.check_gs(now)
            if self.gs.get("Connected"):
                if self.own_scan:
                    self.stop_scan()
                self.scan_next = 0
                self.presence.reset()
            elif self.adapter:
                if self.own_scan and now >= self.scan_deadline:
                    self.stop_scan()
                if not self.own_scan and now >= self.scan_next:
                    self.start_scan(now)
            if self.presence.expire(now):
                LOG.info("Phone no longer nearby; existing GSConnect session left running")
            if self.gs.get("Connected"):
                self.reason = "connected"
            elif not self.adapter:
                self.reason = "bluetooth_unavailable"
            elif not self.gs.get("Paired"):
                self.reason = "target_not_paired"
            elif not self.presence.near:
                self.reason = "waiting_for_phone"
            elif not self.presence.ip:
                self.reason = "waiting_for_phone_wifi"
            else:
                self.check_network(now)
                if not on_local_network(self.presence.ip, self.interfaces):
                    self.reason = "waiting_for_same_lan"
                else:
                    self.reason = "reconnecting"
                    if self.presence.due(now, True, False):
                        self.presence.attempted(now)
                        self.reconnect()
            self.last_error = None
        except (GLib.Error, OSError, ValueError, subprocess.SubprocessError) as exc:
            error = str(exc)
            if error != self.last_error:
                LOG.warning("%s", error)
            self.last_error = error
            self.reason = "waiting_for_service"
        if self.reason != self.last_status:
            LOG.info("State: %s", self.reason)
            self.last_status = self.reason
        self.write_status()
        return GLib.SOURCE_CONTINUE

    def write_status(self):
        snapshot = self.status()
        identity = tuple(snapshot[k] for k in ("state", "nearby", "phone_ipv4", "gsconnect_paired",
                                               "gsconnect_connected", "bluetooth_adapter", "error"))
        now = time.monotonic()
        if identity == self.saved_state and (snapshot["last_seen_seconds"] is None or now - self.saved_at < 30):
            return
        age = snapshot["last_seen_seconds"]
        snapshot["last_seen_at"] = time.time() - age if age is not None else None
        STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = STATE.with_suffix(".tmp")
        temp.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
        os.chmod(temp, 0o600)
        temp.replace(STATE)
        self.saved_state = identity
        self.saved_at = now

    def run(self, seconds=None):
        add_signal(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda *_: (self.loop.quit(), False)[1])
        add_signal(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda *_: (self.loop.quit(), False)[1])
        GLib.timeout_add_seconds(1, self.tick)
        if seconds:
            GLib.timeout_add_seconds(seconds, lambda: (self.loop.quit(), False)[1])
        self.tick()
        try:
            self.loop.run()
        finally:
            self.stop_scan()
            self.reason = "stopped"
            self.write_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--seconds", type=int)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Manually request LAN discovery")
    binding = parser.add_mutually_exclusive_group()
    binding.add_argument("--bind", action="store_true", help="选择手机并显示绑定二维码")
    binding.add_argument("--unbind", action="store_true", help="解除本机绑定并停止监听")
    args = parser.parse_args()
    if args.bind or args.unbind:
        if args.config != str(CONFIG) or args.status or args.refresh or args.dry_run or args.seconds is not None:
            parser.error("绑定管理请单独使用 --bind 或 --unbind")
        from pairing import manage_binding
        manage_binding(CONFIG, STATE, args.unbind)
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.status:
        if STATE.exists():
            snapshot = json.loads(STATE.read_text())
            if snapshot.get("last_seen_at") is not None:
                snapshot["last_seen_seconds"] = round(max(0, time.time() - snapshot["last_seen_at"]), 1)
            print(json.dumps(snapshot, indent=2, ensure_ascii=False))
        else:
            parser.exit(1, "No status yet; service has not run.\n")
        return
    config = load_config(args.config)
    if args.refresh:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        call(bus, APP, ROOT, "org.gtk.Actions", "Activate", GLib.Variant("(sava{sv})", ("refresh", [], {})))
        print("GSConnect discovery requested")
        return
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with STATE.with_suffix(".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, "Watcher already running; use --status or systemctl --user stop nearby-connect.\n")
        Watcher(config, args.dry_run).run(args.seconds)


if __name__ == "__main__":
    main()
