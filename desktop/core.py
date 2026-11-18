"""Proximity policy. A BLE hint can request discovery, never establish trust."""

from dataclasses import dataclass
import ipaddress


def decode_hint(payload):
    """Wire format: version 1 + four IPv4 bytes; zero means no Wi-Fi."""
    data = bytes(payload)
    if len(data) != 5 or data[0] != 1:
        raise ValueError("Unsupported BLE payload")
    address = ipaddress.IPv4Address(data[1:])
    if address.is_unspecified:
        return None
    if address.is_loopback or address.is_multicast or address.is_link_local:
        raise ValueError("Invalid peer address")
    return str(address)


def on_local_network(address, interfaces):
    """Accept unicast peers on active, non-virtual LAN interfaces only."""
    if address is None:
        return False
    peer = ipaddress.IPv4Address(address)
    for interface in interfaces:
        name = interface.get("ifname", "")
        if name.startswith(("lo", "docker", "br-", "virbr", "veth", "tun", "tap")):
            continue
        if "LOWER_UP" not in interface.get("flags", []) or "POINTOPOINT" in interface.get("flags", []):
            continue
        for info in interface.get("addr_info", []):
            if info.get("family") != "inet" or info.get("scope") != "global":
                continue
            local = ipaddress.IPv4Interface(f"{info['local']}/{info['prefixlen']}")
            if peer in local.network and peer not in (local.ip, local.network.network_address, local.network.broadcast_address):
                return True
    return False


@dataclass
class Presence:
    enter_rssi: int = -72
    exit_rssi: int = -82
    lost_after: float = 35
    near: bool = False
    last_seen: float = float("-inf")
    last_good: float = float("-inf")
    last_sample: float = float("-inf")
    rssi: float | None = None
    strong_samples: int = 0
    ip: str | None = None
    next_attempt: float = 0
    attempts: int = 0

    def observe(self, now, rssi, address):
        if not -127 <= rssi <= 20:
            return False
        # Forget old samples before using a new encounter.
        self.expire(now)
        if now - self.last_seen > 5:
            self.rssi = None
            self.strong_samples = 0
        self.last_seen = now
        if address != self.ip:
            self.ip = address
            self.next_attempt = now
            self.attempts = 0
        if now - self.last_sample < 0.6:
            return False
        self.last_sample = now
        self.rssi = rssi if self.rssi is None else 0.6 * rssi + 0.4 * self.rssi
        if self.rssi >= self.exit_rssi:
            self.last_good = now
        if not self.near:
            self.strong_samples = self.strong_samples + 1 if self.rssi >= self.enter_rssi else 0
            if self.strong_samples >= 2:
                self.near = True
                self.next_attempt = now
                self.attempts = 0
                return True
        return False

    def expire(self, now):
        if self.near and now - self.last_good > self.lost_after:
            self.reset()
            return True
        return False

    def reset(self):
        self.near = False
        self.rssi = None
        self.strong_samples = 0
        self.ip = None
        self.last_seen = self.last_good = self.last_sample = float("-inf")
        self.next_attempt = 0
        self.attempts = 0

    def due(self, now, paired, connected):
        return self.near and paired and not connected and now >= self.next_attempt

    def attempted(self, now):
        self.next_attempt = now + (5, 10, 15)[min(self.attempts, 2)]
        self.attempts += 1
