package com.rushd.rx;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/**
 * Gives the camera app a private file to write the prescription photo into (file:// URIs are not
 * allowed between apps). Not exported: the camera app only gets a grant for one photo's URI.
 * Photos are deleted after an hour - they contain patient names and are uploaded right away.
 */
public class CaptureProvider extends ContentProvider {
    static final String AUTHORITY = "com.rushd.rx.captures";
    private static final long KEEP_MILLIS = 60L * 60L * 1000L;

    static Uri newCapture() {
        String name = "rx-" + System.currentTimeMillis() + ".jpg";
        return new Uri.Builder().scheme("content").authority(AUTHORITY).appendPath(name).build();
    }

    static boolean hasPhoto(Context context, Uri uri) {
        try {
            return uri != null && file(context, uri).length() > 0;
        } catch (IllegalArgumentException e) {
            return false;
        }
    }

    static void deleteOld(Context context) {
        File[] files = folder(context).listFiles();
        long cutoff = System.currentTimeMillis() - KEEP_MILLIS;
        if (files != null) {
            for (File f : files) {
                if (f.lastModified() < cutoff) {
                    f.delete();
                }
            }
        }
    }

    private static File folder(Context context) {
        File folder = new File(context.getCacheDir(), "captures");
        folder.mkdirs();
        return folder;
    }

    private static File file(Context context, Uri uri) {
        String name = uri.getLastPathSegment();
        if (!AUTHORITY.equals(uri.getAuthority()) || name == null || !name.matches("rx-[0-9]{1,19}\\.jpg")) {
            throw new IllegalArgumentException("unknown capture");
        }
        return new File(folder(context), name);
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        return ParcelFileDescriptor.open(file(getContext(), uri), ParcelFileDescriptor.parseMode(mode));
    }

    @Override
    public String getType(Uri uri) {
        return "image/jpeg";
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sortOrder) {
        File f = file(getContext(), uri);
        MatrixCursor cursor = new MatrixCursor(new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE});
        cursor.addRow(new Object[] {f.getName(), f.length()});
        return cursor;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] args) {
        return 0;
    }

    @Override
    public int delete(Uri uri, String selection, String[] args) {
        return 0;
    }
}
