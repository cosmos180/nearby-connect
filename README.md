# 靠近互联

让已配对的 Android 手机回到电脑附近、重新接入同一局域网后，自动触发 GSConnect 发现。适用于使用 GNOME 和 GSConnect 的 Linux 电脑。每部手机使用同一个 APK，首次绑定时才生成配置。

## 安装和绑定

1. 在手机安装 KDE Connect，在 GNOME 启用 GSConnect，让两端先在同一局域网完成配对。电脑需要支持低功耗蓝牙扫描，手机需要 Android 8.0 或以上且支持低功耗蓝牙广播。局域网需要允许两端直接通信。
2. 在手机安装签名文件 `nearby-connect.apk`。使用过旧版专用 APK 的用户，先停止旧版广播，再打开新版「靠近互联」。
3. 在电脑准备 Python 3.10+、PyGObject（Gio、GLib）、BlueZ、iproute2、systemd 用户会话和命令 `qrcode-terminal`。Ubuntu 可通过 apt 安装 `python3-gi bluez iproute2 npm`，用 `command -v qrcode-terminal` 确认二维码工具可用。
4. 在已登录 GNOME 的用户终端，进入仓库根目录运行以下命令，按编号选择已配对的手机或平板。

   ```sh
   /usr/bin/python3 scripts/install_desktop.py
   ```

5. 用手机相机扫描终端二维码，选择用「靠近互联」打开并确认绑定。应用内的「扫码绑定电脑」需要支持 ZXing 扫码接口的扫码器。相机无法打开自定义链接时，可复制终端中的完整链接，使用「粘贴绑定码」。
6. 手机确认后回到终端按 Enter 保存，随后在手机点击「开启靠近广播」，授予附近设备权限。当前每端保存一个绑定，重新运行安装程序可更换目标。

## 日常使用和排障

手机通过带通知的 Android 前台服务广播，可退出应用界面或锁屏使用。手机重启后需重新开启。系统限制后台活动时，请检查靠近互联和 KDE Connect 两个应用的后台运行设置。

电脑根据蓝牙信号强度判断接近。发现手机后，使用广播中的 Wi-Fi IPv4 地址触发局域网发现。GSConnect 连接后，监听程序释放自己的扫描请求，断线后恢复扫描。实际重连延时受手机后台策略、无线网络和蓝牙信号影响。

```sh
~/.local/bin/nearby-connect --status
systemctl --user status nearby-connect.service
journalctl --user -u nearby-connect.service -n 50
```

如果始终无法重连，先检查手机是否显示广播中及正确的 Wi-Fi 地址，再确认 GSConnect 可以手动连上同一设备。访客网络的客户端隔离可能阻止局域网连接。

## 隐私和绑定

手机通过蓝牙发送绑定标识和当前 Wi-Fi IPv4 地址，附近的蓝牙接收设备可以读取。绑定标识在重新绑定前保持固定。请只扫描自己电脑显示的码；身份验证和数据传输由 KDE Connect 与 GSConnect 负责。电脑配置保存在 `~/.config/nearby-connect/config.json`。提交问题时请遮盖绑定链接、设备标识、地址和日志中的个人信息。

## 构建和测试

在 Linux 准备 JDK 17，设置 JAVA_HOME，并将 ANDROID_HOME 指向包含 Android Platform 35 和 Build Tools 35.0.0 的 SDK。在仓库根目录执行：

```sh
/usr/bin/python3 -m unittest discover -s tests
python3 scripts/build_apk.py
(cd build && sha256sum -c SHA256SUMS)
```

脚本会生成并验证签名 APK。发布附件使用 build/nearby-connect.apk 和 build/SHA256SUMS。首次构建在用户目录 ~/.local/share/nearby-connect/release-signing/ 创建签名材料。发布者应私下备份该目录以便后续版本沿用同一签名。

## 卸载

手机可在系统设置中卸载「靠近互联」。电脑运行以下命令移除监听服务、启动器和本地绑定。

```sh
systemctl --user disable --now nearby-connect.service
rm -f ~/.config/systemd/user/nearby-connect.service ~/.local/bin/nearby-connect
rm -rf ~/.local/share/nearby-connect/desktop ~/.config/nearby-connect
systemctl --user daemon-reload
```

## 许可

本项目使用 [Apache License 2.0](LICENSE)。
