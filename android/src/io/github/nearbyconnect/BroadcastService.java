package io.github.nearbyconnect;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.AdvertiseCallback;
import android.bluetooth.le.AdvertiseData;
import android.bluetooth.le.AdvertiseSettings;
import android.bluetooth.le.BluetoothLeAdvertiser;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.ParcelUuid;
import java.net.Inet4Address;
import java.util.Arrays;

public final class BroadcastService extends Service {
    private static final String CHANNEL = "nearby";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private BluetoothAdapter adapter;
    private BluetoothLeAdvertiser advertiser;
    private AdvertiseCallback activeCallback;
    private ConnectivityManager connectivity;
    private byte[] currentAddress;
    private boolean receiverRegistered;
    private boolean networkRegistered;
    private boolean destroyed;
    private boolean retryPending;
    private boolean retryBlocked;
    private int failures;
    private final Runnable refresh = () -> {
        retryPending = false;
        advertise();
    };
    private final ConnectivityManager.NetworkCallback networkCallback = new ConnectivityManager.NetworkCallback() {
        @Override public void onAvailable(Network network) { schedule(); }
        @Override public void onLost(Network network) { schedule(); }
        @Override public void onLinkPropertiesChanged(Network network, LinkProperties props) { schedule(); }
    };
    private final BroadcastReceiver bluetoothChanged = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            int state = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR);
            if (state == BluetoothAdapter.STATE_TURNING_OFF || state == BluetoothAdapter.STATE_OFF) {
                handler.removeCallbacks(refresh);
                stopAdvertising();
                status("等待蓝牙开启");
            } else if (state == BluetoothAdapter.STATE_ON) {
                stopAdvertising();
                resetRetry();
                schedule();
            }
        }
    };

    private void resetRetry() {
        handler.removeCallbacks(refresh);
        failures = 0;
        retryPending = false;
        retryBlocked = false;
    }

    private void failure(String reason, int initialSeconds) {
        handler.removeCallbacks(refresh);
        if (initialSeconds == 0) {
            retryBlocked = true;
            status(reason + "；请处理后重新开启");
            return;
        }
        int seconds = Math.min(300, initialSeconds << Math.min(failures, 6));
        failures++;
        retryPending = true;
        status(reason + "，" + seconds + " 秒后重试");
        handler.postDelayed(refresh, seconds * 1000L);
    }

    private void schedule() {
        if (retryPending || retryBlocked || destroyed) return;
        handler.removeCallbacks(refresh);
        handler.postDelayed(refresh, 800);
    }

    private Notification notification(String message) {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Intent stopIntent = new Intent(this, BroadcastService.class).setAction("stop");
        PendingIntent stop = PendingIntent.getService(this, 1, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL)
            .setContentTitle("靠近互联")
            .setContentText(message)
            .setSmallIcon(io.github.nearbyconnect.R.drawable.ic_nearby)
            .setContentIntent(open).setOngoing(true)
            .addAction(new Notification.Action.Builder(null, "停止", stop).build()).build();
    }

    private void status(String message) {
        getSharedPreferences("state", MODE_PRIVATE).edit().putString("status", message).apply();
        getSystemService(NotificationManager.class).notify(1, notification(message));
    }

    @Override public void onCreate() {
        super.onCreate();
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL, "靠近检测运行状态", NotificationManager.IMPORTANCE_LOW));
        Notification initial = notification("正在启动蓝牙广播");
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, initial, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
        else startForeground(1, initial);
        BluetoothManager manager = getSystemService(BluetoothManager.class);
        adapter = manager == null ? null : manager.getAdapter();
        connectivity = getSystemService(ConnectivityManager.class);
        try {
            IntentFilter filter = new IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED);
            if (Build.VERSION.SDK_INT >= 33) registerReceiver(bluetoothChanged, filter, Context.RECEIVER_EXPORTED);
            else registerReceiver(bluetoothChanged, filter);
            receiverRegistered = true;
            connectivity.registerNetworkCallback(new NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), networkCallback, handler);
            networkRegistered = true;
        } catch (RuntimeException error) {
            status("网络状态监听不可用：" + error.getClass().getSimpleName());
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && "stop".equals(intent.getAction())) {
            stopSelf();
            return START_NOT_STICKY;
        }
        resetRetry();
        schedule();
        return START_STICKY;
    }

    private byte[] wifiAddress() {
        Network active = connectivity.getActiveNetwork();
        int best = -1;
        byte[] selected = new byte[4];
        for (Network network : connectivity.getAllNetworks()) {
            NetworkCapabilities caps = connectivity.getNetworkCapabilities(network);
            LinkProperties props = connectivity.getLinkProperties(network);
            if (caps == null || props == null) continue;
            int score = WifiChoice.rank(caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI),
                caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN),
                caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN),
                network.equals(active), caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET));
            if (score < 0 || score <= best) continue;
            for (LinkAddress link : props.getLinkAddresses()) {
                java.net.InetAddress ip = link.getAddress();
                if (ip instanceof Inet4Address && !ip.isAnyLocalAddress() && !ip.isLoopbackAddress()
                    && !ip.isLinkLocalAddress() && !ip.isMulticastAddress()) {
                    selected = ip.getAddress();
                    best = score;
                    break;
                }
            }
        }
        return selected;
    }

    private void stopAdvertising() {
        if (advertiser != null && activeCallback != null) {
            try { advertiser.stopAdvertising(activeCallback); } catch (RuntimeException ignored) { }
        }
        activeCallback = null;
        currentAddress = null;
    }

    private void advertise() {
        if (destroyed) return;
        try {
            if (adapter == null || !adapter.isEnabled()) {
                stopAdvertising();
                status("等待蓝牙开启");
                return;
            }
            byte[] address = wifiAddress();
            if (activeCallback != null && Arrays.equals(currentAddress, address)) return;
            stopAdvertising();
            advertiser = adapter.getBluetoothLeAdvertiser();
            if (advertiser == null) {
                failure("等待蓝牙广播服务就绪", 5);
                return;
            }
            String key = getSharedPreferences("binding", MODE_PRIVATE).getString("uuid", null);
            if (key == null) { stopSelf(); return; }
            ParcelUuid service = ParcelUuid.fromString(key);
            // Keep both legacy packets below 31 bytes. The scan response carries the IP.
            AdvertiseData data = new AdvertiseData.Builder().addServiceUuid(service)
                .setIncludeDeviceName(false).setIncludeTxPowerLevel(false).build();
            byte[] payload = new byte[]{1, address[0], address[1], address[2], address[3]};
            AdvertiseData response = new AdvertiseData.Builder().addServiceData(service, payload).build();
            AdvertiseSettings settings = new AdvertiseSettings.Builder()
                .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_POWER)
                .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_LOW)
                .setConnectable(false).setTimeout(0).build();
            currentAddress = address;
            final String ip = (address[0] & 255) + "." + (address[1] & 255) + "." +
                (address[2] & 255) + "." + (address[3] & 255);
            activeCallback = new AdvertiseCallback() {
                @Override public void onStartSuccess(AdvertiseSettings used) {
                    if (destroyed || activeCallback != this) return;
                    failures = 0;
                    status(ip.equals("0.0.0.0") ? "广播中 · 等待 Wi-Fi" : "广播中 · Wi-Fi " + ip);
                }
                @Override public void onStartFailure(int code) {
                    if (destroyed || activeCallback != this) return;
                    activeCallback = null;
                    currentAddress = null;
                    switch (code) {
                        case ADVERTISE_FAILED_DATA_TOO_LARGE:
                        case ADVERTISE_FAILED_FEATURE_UNSUPPORTED:
                            failure("设备不支持当前广播格式（" + code + "）", 0);
                            break;
                        case ADVERTISE_FAILED_TOO_MANY_ADVERTISERS:
                            failure("系统广播资源已满", 30);
                            break;
                        default:
                            failure("广播服务暂不可用（" + code + "）", 5);
                    }
                }
            };
            status("正在更新蓝牙广播");
            advertiser.startAdvertising(settings, data, response, activeCallback);
        } catch (SecurityException error) {
            stopAdvertising();
            failure("缺少附近设备权限", 0);
        } catch (RuntimeException error) {
            stopAdvertising();
            failure("广播异常：" + error.getClass().getSimpleName(), 5);
        }
    }

    @Override public void onDestroy() {
        destroyed = true;
        handler.removeCallbacksAndMessages(null);
        stopAdvertising();
        if (receiverRegistered) unregisterReceiver(bluetoothChanged);
        if (networkRegistered) connectivity.unregisterNetworkCallback(networkCallback);
        getSharedPreferences("state", MODE_PRIVATE).edit().putString("status", "已停止").apply();
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
