package com.rushd.rx;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.print.PrintAttributes;
import android.print.PrintManager;
import android.provider.MediaStore;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.util.ArrayList;
import java.util.List;

/**
 * رُشد للأندرويد: the Rushd web app from the pharmacy's PC or server, full screen.
 *
 * <p>Adds what a browser tab lacks: the phone camera for prescription photos, Android printing for
 * patient labels, finding the PC on the Wi-Fi, and keeping patient data off screenshots.
 * Written without lambdas: the build dexes with dx (Java 8 bytecode, no invokedynamic).
 */
public class MainActivity extends Activity {
    private static final int PICK_PHOTO = 7;
    private static final String PREFS = "rushd";
    private static final int BRAND = 0xFF00796B;
    private static final int ERROR = 0xFFB3261E;
    private static final int TEXT = 0xFF1F2B29;
    private static final int MUTED = 0xFF5F6E6B;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private WebView web;
    private View offline;
    private boolean pageFailed;
    private String server;
    private ValueCallback<Uri[]> pendingPick;
    private Uri pendingPhoto;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Window window = getWindow();
        // Patient data: no screenshots, screen recordings or previews in the recent-apps list.
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        window.setStatusBarColor(Color.WHITE);
        int bars = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
        if (Build.VERSION.SDK_INT >= 26) {
            window.setNavigationBarColor(Color.WHITE);
            bars |= 0x10; // View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR (API 26)
        }
        window.getDecorView().setSystemUiVisibility(bars);
        root = new FrameLayout(this);
        root.setFitsSystemWindows(true); // Android 15 draws edge to edge; keep clear of the system bars
        root.setBackgroundColor(Color.WHITE);
        setContentView(root);
        CaptureProvider.deleteOld(this);
        server = getSharedPreferences(PREFS, MODE_PRIVATE).getString("server", null);
        if (server == null) {
            showSetup(null);
        } else {
            showWeb();
        }
    }

    // ------------------------------------------------------------------ setup: which Rushd?

    private void showSetup(String message) {
        closeWeb();
        root.removeAllViews();
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        box.setPadding(dp(24), dp(40), dp(24), dp(24));

        final TextView status = label(message == null ? "" : message, 15, ERROR, false);
        final ProgressBar progress = new ProgressBar(this);
        progress.setVisibility(View.GONE);
        final EditText address = new EditText(this);
        address.setHint("مثال: 192.168.1.10");
        address.setSingleLine(true);
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        address.setTextDirection(View.TEXT_DIRECTION_LTR);
        address.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        if (server != null) {
            address.setText(server);
        }
        final Button search = button("ابحث عن رُشد على الواي فاي", true);
        final Button connect = button("اتصال بهذا العنوان", false);
        search.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                discover(status, progress, search, connect);
            }
        });
        connect.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                connectTo(address.getText().toString(), status, progress, search, connect);
            }
        });

        box.addView(label("رُشد", 34, BRAND, true));
        box.addView(label("قارئ الروشتات الذكي", 16, MUTED, false));
        add(box, label("شغّل رُشد على كمبيوتر الصيدلية بملف Share-with-phones، واجعل الموبايل على نفس الواي فاي - "
                + "ثم اضغط «ابحث». أو اكتب عنوان خادم رُشد.", 16, TEXT, false), 20);
        add(box, search, 20);
        add(box, label("أو اكتب العنوان الظاهر على الكمبيوتر:", 15, MUTED, false), 24);
        add(box, address, 6);
        add(box, connect, 10);
        add(box, progress, 16);
        add(box, status, 8);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(box);
        root.addView(scroll);
    }

    private void connectTo(String input, final TextView status, final ProgressBar progress, final Button... buttons) {
        final String origin;
        try {
            origin = ServerAddress.normalize(input);
        } catch (IllegalArgumentException e) {
            status.setText(e.getMessage());
            return;
        }
        busy(true, status, progress, buttons);
        new Thread(new Runnable() {
            @Override
            public void run() {
                final boolean reachable = Discovery.isRushd(origin);
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        busy(false, status, progress, buttons);
                        if (reachable) {
                            save(origin);
                            showWeb();
                        } else {
                            status.setText("تعذر الوصول إلى رُشد على " + origin
                                    + "\nتأكد أن رُشد يعمل على الكمبيوتر وأن الموبايل على نفس الواي فاي.");
                        }
                    }
                });
            }
        }).start();
    }

    private void discover(final TextView status, final ProgressBar progress, final Button... buttons) {
        final List<String> networks = Discovery.localPrefixes();
        if (networks.isEmpty()) {
            status.setText("الموبايل غير متصل بشبكة واي فاي.");
            return;
        }
        busy(true, status, progress, buttons);
        new Thread(new Runnable() {
            @Override
            public void run() {
                List<String> found;
                try {
                    found = Discovery.scan(networks, ServerAddress.DESKTOP_PORT);
                } catch (InterruptedException e) {
                    found = new ArrayList<String>();
                }
                final List<String> result = found;
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        busy(false, status, progress, buttons);
                        if (result.size() == 1) {
                            save(result.get(0));
                            showWeb();
                        } else if (result.isEmpty()) {
                            status.setText("لم يتم العثور على رُشد على هذه الشبكة. تأكد أن Share-with-phones يعمل على "
                                    + "الكمبيوتر وأنكما على نفس الواي فاي، أو اكتب العنوان الظاهر عليه.");
                        } else {
                            choose(result);
                        }
                    }
                });
            }
        }).start();
    }

    private void choose(final List<String> servers) {
        new AlertDialog.Builder(this)
                .setTitle("اختر جهاز رُشد")
                .setItems(servers.toArray(new String[0]), new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        save(servers.get(which));
                        showWeb();
                    }
                })
                .show();
    }

    private void busy(boolean on, TextView status, ProgressBar progress, Button... buttons) {
        if (on) {
            status.setText("");
        }
        progress.setVisibility(on ? View.VISIBLE : View.GONE);
        for (Button b : buttons) {
            b.setEnabled(!on);
        }
    }

    private void save(String origin) {
        server = origin;
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("server", origin).apply();
    }

    // ------------------------------------------------------------------ the web app

    private void showWeb() {
        closeWeb();
        root.removeAllViews();
        web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        settings.setUserAgentString(settings.getUserAgentString() + " RushdAndroid/1.0");
        CookieManager.getInstance().setAcceptCookie(true);
        web.addJavascriptInterface(new Bridge(), "RushdAndroid");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        web.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String agent, String disposition, String mime, long length) {
                toast("حفظ الملفات والتصدير متاح من الكمبيوتر");
            }
        });
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        web.loadUrl(server + "/");
    }

    private void closeWeb() {
        hideOffline();
        if (web != null) {
            root.removeView(web);
            web.destroy();
            web = null;
        }
    }

    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            if (ServerAddress.sameOrigin(server, url)) {
                return false;
            }
            openOutside(url); // the app only ever shows the Rushd server's own pages
            return true;
        }

        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            pageFailed = false;
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            if (pageFailed) {
                return;
            }
            hideOffline();
            // The web app prints patient labels with window.print(); route it to Android printing.
            view.evaluateJavascript("(function(){window.print=function(){RushdAndroid.print()}})()", null);
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                pageFailed = true;
                showOffline();
            }
        }
    }

    /** The only thing a page may ask of the phone: print - and only Rushd's own pages. */
    private class Bridge {
        @JavascriptInterface
        public void print() {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    if (web == null || !ServerAddress.sameOrigin(server, web.getUrl())) {
                        return;
                    }
                    PrintManager printing = (PrintManager) getSystemService(Context.PRINT_SERVICE);
                    printing.print("رُشد - ملصقات", web.createPrintDocumentAdapter("rushd-labels"),
                            new PrintAttributes.Builder().build());
                }
            });
        }
    }

    private class Chrome extends WebChromeClient {
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            if (pendingPick != null) {
                pendingPick.onReceiveValue(null);
            }
            pendingPick = callback;
            CaptureProvider.deleteOld(MainActivity.this);
            pendingPhoto = CaptureProvider.newCapture();
            Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            camera.putExtra(MediaStore.EXTRA_OUTPUT, pendingPhoto);
            camera.setClipData(ClipData.newRawUri("", pendingPhoto));
            camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            // Grants on an intent inside a chooser do not always reach the camera app; grant directly too.
            for (ResolveInfo app : getPackageManager().queryIntentActivities(camera, PackageManager.MATCH_DEFAULT_ONLY)) {
                grantUriPermission(app.activityInfo.packageName, pendingPhoto,
                        Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            }
            Intent request = camera; // the web app's "take a photo" button asks for the camera directly
            if (!params.isCaptureEnabled()) {
                Intent gallery = new Intent(Intent.ACTION_GET_CONTENT);
                gallery.addCategory(Intent.CATEGORY_OPENABLE);
                gallery.setType("image/*");
                request = Intent.createChooser(gallery, "صورة الروشتة");
                request.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[] {camera});
            }
            try {
                startActivityForResult(request, PICK_PHOTO);
            } catch (ActivityNotFoundException e) {
                pendingPick.onReceiveValue(null);
                pendingPick = null;
                toast("لا يوجد تطبيق كاميرا أو صور على هذا الموبايل");
            }
            return true;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode != PICK_PHOTO || pendingPick == null) {
            super.onActivityResult(requestCode, resultCode, data);
            return;
        }
        Uri[] chosen = null;
        if (resultCode == RESULT_OK) {
            if (data != null && data.getData() != null) {
                chosen = new Uri[] {data.getData()};
            } else if (CaptureProvider.hasPhoto(this, pendingPhoto)) {
                chosen = new Uri[] {pendingPhoto};
            }
        }
        pendingPick.onReceiveValue(chosen); // always answer, or the page's file input stops working
        pendingPick = null;
        if (pendingPhoto != null) {
            revokeUriPermission(pendingPhoto, Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        }
    }

    // ------------------------------------------------------------------ when the PC is unreachable

    private void showOffline() {
        if (offline != null) {
            return;
        }
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        box.setGravity(Gravity.CENTER_VERTICAL);
        box.setBackgroundColor(Color.WHITE);
        box.setPadding(dp(24), dp(24), dp(24), dp(24));
        Button retry = button("إعادة المحاولة", true);
        Button change = button("تغيير العنوان", false);
        retry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (web != null) {
                    web.loadUrl(server + "/");
                }
            }
        });
        change.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showSetup(null);
            }
        });
        box.addView(label("تعذر الاتصال برُشد", 24, TEXT, true));
        add(box, label("تأكد أن كمبيوتر الصيدلية مفتوح ورُشد يعمل عليه، وأن الموبايل على نفس الواي فاي.", 16, TEXT, false), 12);
        add(box, label(server, 15, MUTED, false), 8);
        add(box, retry, 24);
        add(box, change, 10);
        offline = box;
        root.addView(box, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private void hideOffline() {
        if (offline != null) {
            root.removeView(offline);
            offline = null;
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && offline == null && web.canGoBack()) {
            web.goBack();
            return;
        }
        if (web == null) {
            super.onBackPressed();
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("رُشد")
                .setMessage("متصل بـ " + server)
                .setPositiveButton("خروج", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        finish();
                    }
                })
                .setNeutralButton("تغيير العنوان", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        showSetup(null);
                    }
                })
                .setNegativeButton("إلغاء", null)
                .show();
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();
    }

    @Override
    protected void onDestroy() {
        closeWeb();
        super.onDestroy();
    }

    // ------------------------------------------------------------------ small helpers

    private void openOutside(String url) {
        Uri uri = Uri.parse(url);
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();
        if (!scheme.equals("https") && !scheme.equals("http") && !scheme.equals("tel") && !scheme.equals("mailto")) {
            return; // never hand intent:, file: or javascript: links to other apps
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException e) {
            toast("لا يوجد تطبيق لفتح هذا الرابط");
        }
    }

    private TextView label(String text, int sp, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        view.setTextColor(color);
        view.setLineSpacing(0, 1.25f);
        if (bold) {
            view.setTypeface(Typeface.DEFAULT_BOLD);
        }
        return view;
    }

    private Button button(String text, boolean primary) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        button.setTextColor(primary ? Color.WHITE : BRAND);
        GradientDrawable shape = new GradientDrawable();
        shape.setCornerRadius(dp(12));
        shape.setColor(primary ? BRAND : Color.WHITE);
        shape.setStroke(dp(primary ? 0 : 1), BRAND);
        button.setBackground(shape);
        button.setMinHeight(dp(52));
        return button;
    }

    private void add(LinearLayout box, View view, int marginTopDp) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(marginTopDp);
        box.addView(view, params);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void toast(String text) {
        Toast.makeText(this, text, Toast.LENGTH_LONG).show();
    }
}
