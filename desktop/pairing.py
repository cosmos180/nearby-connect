"""Select an existing GSConnect pairing and print its local provisioning code."""
import subprocess
import uuid
from gi.repository import Gio
from nearby_connect import APP, ROOT, DEVICE, call


def phones(objects):
    return [props[DEVICE] for props in objects.values() if DEVICE in props
            and props[DEVICE].get("Paired") and props[DEVICE].get("Type") in ("phone", "tablet")]


def choose():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    devices = phones(call(bus, APP, ROOT, "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")[0])
    if not devices:
        raise SystemExit("请先在 GSConnect 中配对手机，再重新运行。")
    for i, dev in enumerate(devices, 1):
        print(f"{i}. {dev['Name']!r} ({dev['Id'][-8:]})")
    index = input("选择已配对的设备编号：").strip()
    if not index.isascii() or not index.isdigit() or not 1 <= int(index) <= len(devices):
        raise SystemExit("无效选择，配置未写入。")
    dev = devices[int(index) - 1]
    key = str(uuid.uuid4())
    link = "nearbyconnect://bind/v1/" + key
    print("请用选中的手机扫描，或复制链接到“粘贴绑定码”。", flush=True)
    subprocess.run(["qrcode-terminal"], input=link + "\n", text=True, check=True)
    print(link, flush=True)
    if input("手机确认绑定后按 Enter 保存；输入其他内容取消："):
        raise SystemExit("已取消电脑端配置。")
    return {"name": dev["Name"], "device_id": dev["Id"], "service_uuid": key}


def save_binding(config, profile):
    import json
    import tempfile
    from pathlib import Path
    config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=config.parent, delete=False) as temp:
        json.dump(profile, temp)
    Path(temp.name).replace(config)


def manage_binding(config, state, unbind):
    if unbind:
        if input("解除本机靠近绑定并停止监听？输入 y 确认：").strip().lower() != "y":
            print("已取消。")
            return
        subprocess.run(["systemctl", "--user", "disable", "--now", "nearby-connect.service"], check=True)
        config.unlink(missing_ok=True)
        state.unlink(missing_ok=True)
        print("电脑端已解绑。")
    else:
        save_binding(config, choose())
        subprocess.run(["systemctl", "--user", "enable", "nearby-connect.service"], check=True)
        subprocess.run(["systemctl", "--user", "restart", "nearby-connect.service"], check=True)
