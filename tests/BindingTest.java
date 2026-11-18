package io.github.nearbyconnect;

class BindingTest {
    public static void main(String[] args) {
        String key = "00000000-0000-4000-8000-000000000001";
        String link = "nearbyconnect://bind/v1/" + key;
        assert key.equals(Binding.parse(link));
        assert Binding.parse(link + "/extra") == null;
        assert Binding.parse(key) == null;
        assert Binding.parse(null) == null;
    }
}
