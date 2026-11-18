package io.github.nearbyconnect;

import android.Manifest;
import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.ArrayList;

public final class MainActivity extends Activity {
    private TextView status;
    private final Handler handler = new Handler();
    private final Runnable update = new Runnable() {
        @Override public void run() {
            status.setText(getSharedPreferences("state", MODE_PRIVATE)
                .getString("status", "尚未开启"));
            handler.postDelayed(this, 2000);
        }
    };

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private TextView text(String value, int size) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(Color.rgb(30, 50, 48));
        view.setPadding(0, dp(10), 0, dp(10));
        return view;
    }

    private void button(LinearLayout parent, String title, View.OnClickListener action) {
        Button button = new Button(this);
        button.setText(title);
        button.setAllCaps(false);
        button.setOnClickListener(action);
        parent.addView(button, new LinearLayout.LayoutParams(-1, dp(56)));
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        ScrollView scroll = new ScrollView(this);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(24), dp(36), dp(24), dp(24));
        layout.setBackgroundColor(Color.rgb(243, 248, 245));
        scroll.addView(layout);
        layout.addView(text("靠近，即可重连", 28));
        layout.addView(text("为已配对的 KDE Connect / GSConnect 提供蓝牙靠近提示。", 16));
        status = text("", 18);
        layout.addView(status);
        button(layout, "开启靠近广播", v -> enable());
        button(layout, "停止广播", v -> {
            stopService(new Intent(this, BroadcastService.class));
            getSharedPreferences("state", MODE_PRIVATE).edit().putString("status", "已停止").apply();
        });
        button(layout, "打开 KDE Connect", v -> {
            Intent launch = getPackageManager().getLaunchIntentForPackage("org.kde.kdeconnect_tp");
            if (launch != null) startActivity(launch);
            else status.setText("未找到 KDE Connect，请先安装并与电脑配对。");
        });
        button(layout, "本应用后台运行设置", v -> appSettings(getPackageName()));
        button(layout, "KDE Connect 后台运行设置", v -> appSettings("org.kde.kdeconnect_tp"));
        layout.addView(text("使用条件\n手机和电脑接入同一局域网，蓝牙保持开启。请在系统设置中允许这两个应用后台运行；重启手机后需要重新点一次开启。", 15));
        layout.addView(text("蓝牙只发送本机专用标识和 Wi-Fi IPv4 地址，不发送文件或消息。现有 GSConnect 配对负责身份验证。本应用不申请互联网、定位、短信或通讯录权限。", 14));
        button(layout, "扫码绑定电脑", v -> {
            Intent scan = new Intent("com.google.zxing.client.android.SCAN");
            scan.putExtra("SCAN_MODE", "QR_CODE_MODE");
            try { startActivityForResult(scan, 3); }
            catch (android.content.ActivityNotFoundException e) { pasteBinding(); }
        });
        button(layout, "粘贴绑定码", v -> pasteBinding());
        String bound = getSharedPreferences("binding", MODE_PRIVATE).getString("uuid", null);
        layout.addView(text(bound == null ? "尚未绑定电脑" : "已配置靠近广播", 14));
        if (state == null && Intent.ACTION_VIEW.equals(getIntent().getAction())) {
            confirmBinding(getIntent().getDataString());
        }
        setContentView(scroll);
    }

    private void pasteBinding() {
        android.widget.EditText field = new android.widget.EditText(this);
        field.setSingleLine(true);
        field.setHint("粘贴电脑显示的完整绑定链接");
        new android.app.AlertDialog.Builder(this).setTitle("绑定电脑").setView(field)
            .setPositiveButton("继续", (d, w) -> confirmBinding(field.getText().toString().trim()))
            .setNegativeButton("取消", null).show();
    }

    private void confirmBinding(String link) {
        String key = Binding.parse(link);
        if (key == null) {
            new android.app.AlertDialog.Builder(this).setMessage("绑定码无效，请扫描电脑生成的二维码。")
                .setPositiveButton("确定", null).show();
            return;
        }
        new android.app.AlertDialog.Builder(this).setTitle("使用这台电脑的绑定码？")
            .setMessage("请确认二维码来自自己的电脑。确认后会替换之前的绑定。")
            .setNegativeButton("取消", null).setPositiveButton("绑定", (d, w) -> {
                stopService(new Intent(this, BroadcastService.class));
                getSharedPreferences("binding", MODE_PRIVATE).edit().putString("uuid", key).apply();
                setIntent(new Intent());
                recreate();
            }).show();
    }

    private void appSettings(String packageName) {
        try {
            startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.parse("package:" + packageName)));
        } catch (RuntimeException error) {
            status.setText("无法打开应用设置：" + error.getMessage());
        }
    }

    private boolean bluetoothPermissions() {
        return Build.VERSION.SDK_INT < 31 ||
            (checkSelfPermission(Manifest.permission.BLUETOOTH_ADVERTISE) == PackageManager.PERMISSION_GRANTED &&
             checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED);
    }

    private void enable() {
        if (!getSharedPreferences("binding", MODE_PRIVATE).contains("uuid")) {
            pasteBinding();
            return;
        }
        ArrayList<String> permissions = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= 31) {
            for (String permission : new String[]{Manifest.permission.BLUETOOTH_ADVERTISE, Manifest.permission.BLUETOOTH_CONNECT}) {
                if (checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) permissions.add(permission);
            }
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS);
        }
        if (!permissions.isEmpty()) {
            requestPermissions(permissions.toArray(new String[0]), 1);
            return;
        }
        startBroadcast();
    }

    private void startBroadcast() {
        if (!bluetoothPermissions()) {
            status.setText("需要允许附近设备权限，才能发出蓝牙广播。");
            return;
        }
        BluetoothManager manager = getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null) { status.setText("此设备没有可用的蓝牙适配器。"); return; }
        if (!adapter.isEnabled()) {
            startActivityForResult(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE), 2);
            return;
        }
        try {
            startForegroundService(new Intent(this, BroadcastService.class));
        } catch (RuntimeException error) {
            status.setText("启动失败：" + error.getMessage());
        }
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == 1) startBroadcast();
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 3 && result == RESULT_OK && data != null) confirmBinding(data.getStringExtra("SCAN_RESULT"));
        if (request == 2 && result == RESULT_OK) startBroadcast();
    }

    @Override protected void onResume() { super.onResume(); handler.post(update); }
    @Override protected void onPause() { handler.removeCallbacks(update); super.onPause(); }
}
