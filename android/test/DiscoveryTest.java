package com.rushd.rx;

import java.util.Arrays;
import java.util.List;

/**
 * Runs Discovery against a real Rushd server on this machine.
 *
 * <p>usage: java com.rushd.rx.DiscoveryTest PORT  (a Rushd server must listen on 127.0.0.1:PORT)
 */
public final class DiscoveryTest {
    public static void main(String[] args) throws Exception {
        int port = Integer.parseInt(args[0]);
        String origin = "http://127.0.0.1:" + port;
        if (!Discovery.isRushd(origin)) {
            throw new AssertionError("Rushd not recognised at " + origin);
        }
        if (Discovery.isRushd("http://127.0.0.1:" + (port + 1))) {
            throw new AssertionError("a closed port was taken for Rushd");
        }
        long start = System.currentTimeMillis();
        List<String> found = Discovery.scan(Arrays.asList("127.0.0."), port);
        long seconds = (System.currentTimeMillis() - start) / 1000;
        if (!found.contains(origin)) {
            throw new AssertionError("scan missed " + origin + ": " + found);
        }
        System.out.println("DiscoveryTest: found " + found + " in " + seconds + "s; local prefixes " + Discovery.localPrefixes());
    }
}
