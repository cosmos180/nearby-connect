package io.github.nearbyconnect;

import android.app.Activity;
import android.content.Intent;
import android.hardware.Camera;
import android.os.Bundle;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.widget.LinearLayout;
import android.widget.TextView;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.ReaderException;
import com.google.zxing.common.HybridBinarizer;
import com.google.zxing.qrcode.QRCodeReader;
import java.io.IOException;
import java.util.List;

public final class ScanActivity extends Activity implements SurfaceHolder.Callback, Camera.PreviewCallback {
    private Camera camera;
    private SurfaceHolder surface;
    private boolean resumed;
    private TextView hint;
    private final QRCodeReader reader = new QRCodeReader();

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        hint = new TextView(this);
        hint.setText("请将电脑上的绑定二维码对准镜头");
        layout.addView(hint);
        SurfaceView preview = new SurfaceView(this);
        layout.addView(preview, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(layout);
        preview.getHolder().addCallback(this);
    }

    @Override public void surfaceCreated(SurfaceHolder holder) { surface = holder; open(); }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {}
    @Override public void surfaceDestroyed(SurfaceHolder holder) { surface = null; close(); }
    @Override protected void onResume() { super.onResume(); resumed = true; open(); }
    @Override protected void onPause() { resumed = false; close(); super.onPause(); }

    private void open() {
        if (!resumed || surface == null || camera != null) return;
        try {
            camera = Camera.open();
            if (camera == null) throw new IllegalStateException();
            Camera.Parameters params = camera.getParameters();
            List<String> modes = params.getSupportedFocusModes();
            if (modes != null && modes.contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE))
                params.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);
            camera.setParameters(params);
            Camera.CameraInfo info = new Camera.CameraInfo();
            for (int id = 0; id < Camera.getNumberOfCameras(); id++) {
                Camera.getCameraInfo(id, info);
                if (info.facing == Camera.CameraInfo.CAMERA_FACING_BACK) break;
            }
            int rotation = getWindowManager().getDefaultDisplay().getRotation() * 90;
            camera.setDisplayOrientation((info.orientation - rotation + 360) % 360);
            camera.setPreviewDisplay(surface);
            camera.startPreview();
            camera.setOneShotPreviewCallback(this);
        } catch (IOException | RuntimeException e) {
            close();
            hint.setText("无法打开相机，请返回后重试，或使用粘贴绑定码。");
        }
    }

    private void close() {
        if (camera != null) {
            camera.setOneShotPreviewCallback(null);
            camera.release();
            camera = null;
        }
    }

    @Override public void onPreviewFrame(byte[] frame, Camera source) {
        if (source != camera || isFinishing()) return;
        Camera.Size size = source.getParameters().getPreviewSize();
        try {
            if (frame != null) {
                PlanarYUVLuminanceSource image = new PlanarYUVLuminanceSource(frame, size.width,
                    size.height, 0, 0, size.width, size.height, false);
                String link = reader.decode(new BinaryBitmap(new HybridBinarizer(image))).getText();
                if (Binding.parse(link) != null) {
                    setResult(RESULT_OK, new Intent().putExtra("SCAN_RESULT", link));
                    finish();
                    return;
                }
                hint.setText("这不是靠近互联绑定码，请对准电脑上的二维码");
            }
        } catch (ReaderException ignored) {
            // A preview frame need not contain a complete QR code.
        } finally { reader.reset(); }
        hint.postDelayed(() -> {
            if (camera == source && !isFinishing()) source.setOneShotPreviewCallback(this);
        }, 150);
    }
}
