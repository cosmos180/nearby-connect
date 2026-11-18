package io.github.nearbyconnect;

import java.util.regex.Pattern;

final class Binding {
    private static final String PREFIX = "nearbyconnect://bind/v1/";
    private static final Pattern UUID4 = Pattern.compile("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");
    static String parse(String text) {
        if (text == null || !text.startsWith(PREFIX)) return null;
        String value = text.substring(PREFIX.length());
        return UUID4.matcher(value).matches() ? value : null;
    }
}
