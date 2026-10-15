package com.rushd.rx;

import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.net.SocketException;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/** Finds the pharmacy PC running Rushd on the phone's Wi-Fi, so nobody has to type an address. */
final class Discovery {
    private Discovery() {}

    /** Rushd answers GET /api/health with {"status":"ok"}. */
    static boolean isRushd(String origin) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(origin + "/api/health").openConnection();
            connection.setConnectTimeout(2500);
            connection.setReadTimeout(2500);
            connection.setInstanceFollowRedirects(false);
            if (connection.getResponseCode() != 200) {
                return false;
            }
            InputStream in = connection.getInputStream();
            byte[] buffer = new byte[256];
            int read = in.read(buffer);
            in.close();
            return read > 0 && new String(buffer, 0, read, "UTF-8").replace(" ", "").contains("\"status\":\"ok\"");
        } catch (IOException e) {
            return false;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    /** "192.168.1." for each Wi-Fi/Ethernet IPv4 network this phone is on (never mobile data). */
    static List<String> localPrefixes() {
        Set<String> wifi = new LinkedHashSet<String>();
        Set<String> other = new LinkedHashSet<String>();
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            while (interfaces != null && interfaces.hasMoreElements()) {
                NetworkInterface nic = interfaces.nextElement();
                if (!nic.isUp() || nic.isLoopback()) {
                    continue;
                }
                String name = nic.getName().toLowerCase();
                boolean lan = name.startsWith("wlan") || name.startsWith("eth") || name.startsWith("en") || name.startsWith("ap");
                Enumeration<InetAddress> addresses = nic.getInetAddresses();
                while (addresses.hasMoreElements()) {
                    InetAddress address = addresses.nextElement();
                    if (address instanceof Inet4Address && address.isSiteLocalAddress()) {
                        String ip = address.getHostAddress();
                        (lan ? wifi : other).add(ip.substring(0, ip.lastIndexOf('.') + 1));
                    }
                }
            }
        } catch (SocketException e) {
            // no network information: the pharmacist can still type the address
        }
        return new ArrayList<String>(wifi.isEmpty() ? other : wifi);
    }

    /** Every Rushd on the given /24 networks (e.g. "192.168.1."), as origins. */
    static List<String> scan(List<String> prefixes, final int port) throws InterruptedException {
        final List<String> found = Collections.synchronizedList(new ArrayList<String>());
        ExecutorService pool = Executors.newFixedThreadPool(48);
        for (String prefix : prefixes) {
            for (int i = 1; i <= 254; i++) {
                final String host = prefix + i;
                pool.execute(new Runnable() {
                    @Override
                    public void run() {
                        Socket socket = new Socket();
                        try {
                            socket.connect(new InetSocketAddress(host, port), 400);
                        } catch (IOException e) {
                            return;
                        } finally {
                            try {
                                socket.close();
                            } catch (IOException ignored) {
                                // closing an unconnected socket
                            }
                        }
                        String origin = "http://" + host + ":" + port;
                        if (isRushd(origin)) {
                            found.add(origin);
                        }
                    }
                });
            }
        }
        pool.shutdown();
        pool.awaitTermination(30, TimeUnit.SECONDS);
        pool.shutdownNow();
        List<String> result = new ArrayList<String>(found);
        Collections.sort(result);
        return result;
    }
}
