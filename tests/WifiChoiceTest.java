package io.github.nearbyconnect;

class WifiChoiceTest {
    public static void main(String[] args) {
        int physical = WifiChoice.rank(true, false, true, false, true);
        assert physical >= 0;
        assert WifiChoice.rank(true, true, false, true, true) < 0;
        assert WifiChoice.rank(true, false, false, true, true) < 0;
        assert WifiChoice.rank(false, false, true, true, true) < 0;
        assert WifiChoice.rank(true, false, true, false, false) >= 0;
        assert WifiChoice.rank(true, false, true, true, false) > physical;
    }
}
