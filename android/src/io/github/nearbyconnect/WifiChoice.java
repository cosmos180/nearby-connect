package io.github.nearbyconnect;

final class WifiChoice {
    static int rank(boolean wifi, boolean vpn, boolean notVpn, boolean active, boolean internet) {
        if (!wifi || vpn || !notVpn) return -1;
        return (active ? 2 : 0) + (internet ? 1 : 0);
    }
}
