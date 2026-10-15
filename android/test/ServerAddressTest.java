package com.rushd.rx;

/** Plain-JVM checks for ServerAddress; run by android/build_apk.py before every build. */
public final class ServerAddressTest {
    private static int checks;

    private static void eq(String expected, String actual) {
        checks++;
        if (!expected.equals(actual)) {
            throw new AssertionError("expected " + expected + " but got " + actual);
        }
    }

    private static void rejects(String input) {
        checks++;
        try {
            String got = ServerAddress.normalize(input);
            throw new AssertionError("should reject " + input + " but got " + got);
        } catch (IllegalArgumentException expected) {
            // ok
        }
    }

    private static void truth(boolean expected, boolean actual, String what) {
        checks++;
        if (expected != actual) {
            throw new AssertionError(what + ": expected " + expected);
        }
    }

    public static void main(String[] args) {
        // What pharmacists type for the desktop version on the pharmacy Wi-Fi.
        eq("http://192.168.1.10:8000", ServerAddress.normalize("192.168.1.10"));
        eq("http://192.168.1.10:8000", ServerAddress.normalize(" 192.168.1.10:8000 "));
        eq("http://192.168.1.10:8001", ServerAddress.normalize("http://192.168.1.10:8001/#/read"));
        eq("http://10.0.0.5:8000", ServerAddress.normalize("10.0.0.5"));
        eq("http://172.20.1.2:8000", ServerAddress.normalize("172.20.1.2"));
        eq("http://pharmacy-pc.local", ServerAddress.normalize("pharmacy-pc.local"));
        // A real server on the internet: https is assumed, and required.
        eq("https://rx.example.com", ServerAddress.normalize("rx.example.com"));
        eq("https://rx.example.com", ServerAddress.normalize("HTTPS://RX.Example.com:443/#/history"));
        eq("https://rx.example.com:8443", ServerAddress.normalize("https://rx.example.com:8443"));
        rejects("http://rx.example.com");          // cleartext over the internet
        rejects("http://8.8.8.8:8000");            // public IP without TLS
        rejects("http://172.32.0.1");              // just outside 172.16/12
        rejects("ftp://192.168.1.10");
        rejects("");
        rejects("   ");
        rejects("https://user:pass@rx.example.com"); // credentials in the URL
        rejects("http://192.168.1.10:70000");

        truth(true, ServerAddress.sameOrigin("http://192.168.1.10:8000", "http://192.168.1.10:8000/#/rx/abc"), "same");
        truth(false, ServerAddress.sameOrigin("http://192.168.1.10:8000", "http://192.168.1.10:8001/"), "port");
        truth(false, ServerAddress.sameOrigin("https://rx.example.com", "http://rx.example.com/"), "scheme");
        truth(true, ServerAddress.sameOrigin("https://rx.example.com", "https://RX.example.com:443/api"), "default port");
        truth(false, ServerAddress.sameOrigin("https://rx.example.com", "https://rx.example.com.evil.io/"), "suffix");
        truth(false, ServerAddress.sameOrigin("https://rx.example.com", "javascript:alert(1)"), "javascript");
        truth(false, ServerAddress.sameOrigin(null, "https://rx.example.com"), "no server");

        truth(true, ServerAddress.isPrivateHost("192.168.0.1"), "192.168");
        truth(false, ServerAddress.isPrivateHost("192.169.0.1"), "192.169");
        truth(false, ServerAddress.isPrivateHost("example.com"), "domain");
        System.out.println("ServerAddressTest: " + checks + " checks passed");
    }
}
