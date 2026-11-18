#!/usr/bin/python3
"""Install this user's watcher and enable its graphical-session service."""
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
DEST = HOME / ".local/share/nearby-connect/desktop"
CONFIG = HOME / ".config/nearby-connect/config.json"
UNIT = HOME / ".config/systemd/user/nearby-connect.service"
LAUNCHER = HOME / ".local/bin/nearby-connect"


def main():
    import sys
    sys.path.insert(0, str(ROOT / "desktop"))
    from pairing import choose
    profile = choose()
    DEST.mkdir(parents=True, exist_ok=True)
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for file in (ROOT / "desktop").glob("*.py"):
        shutil.copy2(file, DEST / file.name)
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", dir=CONFIG.parent, delete=False) as temp:
        json.dump(profile, temp)
    Path(temp.name).replace(CONFIG)
    CONFIG.chmod(0o600)
    LAUNCHER.parent.mkdir(parents=True, exist_ok=True)
    # Keep the program next to core.py so direct invocation also finds its module.
    LAUNCHER.write_text('#!/bin/sh\nexec /usr/bin/python3 "$HOME/.local/share/nearby-connect/desktop/nearby_connect.py" "$@"\n')
    LAUNCHER.chmod(0o755)
    UNIT.parent.mkdir(parents=True, exist_ok=True)
    UNIT.write_text("""[Unit]
Description=Nearby Connect BLE proximity and GSConnect reconnect
After=graphical-session.target
PartOf=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/.local/share/nearby-connect/desktop/nearby_connect.py
Environment=PYTHONDONTWRITEBYTECODE=1
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
UMask=0077

[Install]
WantedBy=graphical-session.target
""")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "nearby-connect.service"], check=True)
    subprocess.run(["systemctl", "--user", "restart", "nearby-connect.service"], check=True)
    print("Installed; inspect with nearby-connect --status")


if __name__ == "__main__":
    main()
