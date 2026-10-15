package com.rushd.rx;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/**
 * The Rushd server the app talks to, as an origin such as {@code http://192.168.1.10:8000}.
 *
 * <p>Plain Java (no Android classes) so it is unit-tested on the JVM. Plain http is accepted only
 * inside private networks - the desktop version on the pharmacy Wi-Fi; anything on the internet must
 * be https.
 */
final class ServerAddress {
    static final int DESKTOP_PORT = 8000;

    private ServerAddress() {}

    /** Turns what a pharmacist types ("192.168.1.10", "rx.example.com/#/read") into an origin. */
    static String normalize(String input) {
        String text = input == null ? "" : input.trim();
        if (text.isEmpty()) {
            throw new IllegalArgumentException("اكتب عنوان رُشد أولاً");
        }
        if (!text.contains("://")) {
            String host = text.split("[/:?#]", 2)[0];
            text = (isPrivateHost(host) ? "http://" : "https://") + text;
        }
        URI uri;
        try {
            uri = new URI(text);
        } catch (URISyntaxException e) {
            throw new IllegalArgumentException("العنوان غير صحيح");
        }
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        String host = uri.getHost() == null ? "" : uri.getHost().toLowerCase(Locale.ROOT);
        if (!scheme.equals("http") && !scheme.equals("https")) {
            throw new IllegalArgumentException("العنوان يجب أن يبدأ بـ http أو https");
        }
        if (host.isEmpty() || uri.getUserInfo() != null) {
            throw new IllegalArgumentException("العنوان غير صحيح");
        }
        if (scheme.equals("http") && !isPrivateHost(host)) {
            throw new IllegalArgumentException("الاتصال عبر الإنترنت يجب أن يكون مشفراً (https)");
        }
        int port = uri.getPort();
        if (port == -1 && scheme.equals("http") && isIPv4(host)) {
            port = DESKTOP_PORT; // what Start-Rushd / Share-with-phones listen on
        }
        if (port == 0 || port > 65535) {
            throw new IllegalArgumentException("رقم المنفذ غير صحيح");
        }
        boolean defaultPort = port == -1 || (scheme.equals("http") && port == 80) || (scheme.equals("https") && port == 443);
        return scheme + "://" + host + (defaultPort ? "" : ":" + port);
    }

    /** True when {@code url} belongs to the server; everything else opens outside the app. */
    static boolean sameOrigin(String origin, String url) {
        if (origin == null || url == null) {
            return false;
        }
        try {
            URI a = new URI(origin);
            URI b = new URI(url);
            return a.getScheme() != null
                    && a.getScheme().equalsIgnoreCase(b.getScheme())
                    && a.getHost() != null
                    && a.getHost().equalsIgnoreCase(b.getHost())
                    && effectivePort(a) == effectivePort(b);
        } catch (URISyntaxException e) {
            return false;
        }
    }

    private static int effectivePort(URI uri) {
        if (uri.getPort() != -1) {
            return uri.getPort();
        }
        return "https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80;
    }

    static boolean isIPv4(String host) {
        String[] parts = host.split("\\.", -1);
        if (parts.length != 4) {
            return false;
        }
        for (String part : parts) {
            if (part.isEmpty() || part.length() > 3 || !part.matches("[0-9]+") || Integer.parseInt(part) > 255) {
                return false;
            }
        }
        return true;
    }

    /** Addresses that can only be reached inside a local network (RFC 1918, loopback, .local). */
    static boolean isPrivateHost(String host) {
        String h = host.toLowerCase(Locale.ROOT);
        if (h.equals("localhost") || h.endsWith(".local")) {
            return true;
        }
        if (!isIPv4(h)) {
            return false;
        }
        String[] p = h.split("\\.");
        int a = Integer.parseInt(p[0]);
        int b = Integer.parseInt(p[1]);
        return a == 10 || a == 127 || (a == 192 && b == 168) || (a == 172 && b >= 16 && b <= 31);
    }
}
