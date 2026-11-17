package net.shitu.collector;

import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.provider.MediaStore;
import android.util.Base64;
import androidx.core.content.FileProvider;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

@CapacitorPlugin(name="NativeGallery")
public class NativeGalleryPlugin extends Plugin {
    @PluginMethod
    public void save(PluginCall call) {
        getBridge().execute(() -> {
            Uri pending = null;
            try {
                String name = call.getString("name", "image.png").replaceAll("[^a-zA-Z0-9._-]", "_");
                String mime = call.getString("mime", "image/png");
                String data = call.getString("data", "");
                if (!mime.matches("image/(png|jpeg|webp|gif)") || data.length() > 36 * 1024 * 1024) {
                    call.reject("图片格式或大小不支持"); return;
                }
                byte[] bytes = Base64.decode(data, Base64.DEFAULT);
                if (Boolean.TRUE.equals(call.getBoolean("share", false))) {
                    File dir = new File(getContext().getCacheDir(), "shares");
                    if (!dir.exists() && !dir.mkdirs()) throw new java.io.IOException();
                    File[] oldFiles = dir.listFiles();
                    if (oldFiles != null) for (File old : oldFiles) {
                        if (old.lastModified() < System.currentTimeMillis() - 3600000) old.delete();
                    }
                    File file = new File(dir, name);
                    try (OutputStream output = new FileOutputStream(file)) { output.write(bytes); }
                    Uri uri = FileProvider.getUriForFile(getContext(), getContext().getPackageName()+".fileprovider", file);
                    Intent intent = new Intent(Intent.ACTION_SEND).setType(mime)
                        .putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    getActivity().runOnUiThread(() -> {
                        try { getActivity().startActivity(Intent.createChooser(intent, "分享图片")); call.resolve(); }
                        catch (Exception e) { call.reject("没有可用的分享应用"); }
                    });
                } else {
                    ContentValues values = new ContentValues();
                    values.put(MediaStore.Images.Media.DISPLAY_NAME, name);
                    values.put(MediaStore.Images.Media.MIME_TYPE, mime);
                    values.put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/Shitu");
                    values.put(MediaStore.Images.Media.IS_PENDING, 1);
                    pending = getContext().getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
                    if (pending == null) throw new java.io.IOException();
                    try (OutputStream output = getContext().getContentResolver().openOutputStream(pending)) {
                        if (output == null) throw new java.io.IOException();
                        output.write(bytes);
                    }
                    values.clear(); values.put(MediaStore.Images.Media.IS_PENDING, 0);
                    getContext().getContentResolver().update(pending, values, null, null);
                    call.resolve();
                }
            } catch (Exception e) {
                if (pending != null) getContext().getContentResolver().delete(pending, null, null);
                call.reject("保存失败，请检查设备空间和相册可用性");
            }
        });
    }
}
