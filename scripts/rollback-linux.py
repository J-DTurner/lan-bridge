#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lanbridge.config import state_dir, read_json


def main():
    install = read_json(state_dir() / "last-install.json")
    if not install:
        raise SystemExit("No completed Lan Bridge activation to roll back")
    manifest = read_json(Path(install["backup"]) / "manifest.json")
    subprocess.run(["systemctl", "--user", "disable", "--now", "lan-bridge.service"], check=False)
    for item in reversed(manifest["files"]):
        path = Path(item["path"])
        if path.name == "hyprland.lua":
            content = path.read_text()
            for module in ("hypr.lanbridge", "lanbridge"):
                marker = f'\n-- BEGIN LAN BRIDGE\nrequire("{module}")\n-- END LAN BRIDGE\n'
                content = content.replace(marker, "\n")
            path.write_text(content)
        elif item["saved"]:
            shutil.copy2(item["saved"], path)
        else:
            path.unlink(missing_ok=True)
    subprocess.run(["hyprctl", "reload"], check=True)
    result = subprocess.run(["hyprctl", "configerrors"], check=True, capture_output=True, text=True)
    if result.stdout.strip() not in ("", "ok"):
        raise SystemExit(result.stdout)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    if manifest["input_enabled"]:
        subprocess.run(["systemctl", "--user", "enable", "lan-mouse.service"], check=True)
    if manifest["input_active"]:
        subprocess.run(["systemctl", "--user", "start", "lan-mouse.service"], check=True)
    print("Restored the previous input/sidebar setup. Shared and received files were retained.")


if __name__ == "__main__":
    main()
