#!/usr/bin/env python3
"""Stage without desktop IPC; activation validates native Hyprland with rollback."""
from __future__ import annotations
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from lanbridge.config import atomic_json, home_dir, state_dir, read_json, own_fingerprint

MARKER = '\n-- BEGIN LAN BRIDGE\nrequire("hypr.lanbridge")\n-- END LAN BRIDGE\n'
LEGACY_MARKER = '\n-- BEGIN LAN BRIDGE\nrequire("lanbridge")\n-- END LAN BRIDGE\n'


def add_hyprland_module(content):
    # Omarchy's bootstrap searches ~/.config/?.lua; the module lives in hypr/.
    for block in (MARKER, LEGACY_MARKER):
        content = content.replace(block, "")
    return content.rstrip() + "\n" + MARKER


def command(*args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=30)
    if check and result.returncode:
        reason = result.stderr.strip() or f"exit status {result.returncode}"
        raise RuntimeError(f"{' '.join(args)}: {reason}")
    return result


def wait_for_connection(since, timeout=15):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = read_json(state_dir() / "status.json", {})
        if latest.get("updated", 0) >= since and latest.get("connected"):
            return latest
        time.sleep(0.5)
    return latest


def stage(args):
    if sys.platform != "linux":
        raise SystemExit("Use install-windows.ps1 on Windows")
    identity = Path.home() / ".config/lan-mouse/lan-mouse.pem"
    source_config = identity.parent / "config.toml"
    if not identity.exists():
        raise SystemExit("Pair Lan Mouse first; its existing certificate is required")
    own_fingerprint(identity)  # validate the public certificate without printing key data
    config_file = home_dir() / "config.json"
    config = read_json(config_file)
    if not config:
        trust = tomllib.loads(source_config.read_text()).get("authorized_fingerprints", {})
        if not args.host or len(trust) != 1:
            raise SystemExit("For first staging provide --host WINDOWS_IP and exactly one approved Lan Mouse peer")
        config = {"identity": str(identity), "host": args.host, "port": 4242,
                  "peer_fingerprint": next(iter(trust)).replace(":", "").lower(),
                  "shared": str(Path.home() / "Lan Bridge Shared"),
                  "inbox": str(Path.home() / "Downloads/Lan Bridge Inbox"),
                  "clipboard": True, "sync": True, "audio": True,
                  "workspaces": [6, 7], "fps": 15, "max_width": 1920}
        atomic_json(config_file, config)
    dest = Path.home() / ".local/share/lan-bridge/app"
    if SOURCE.resolve() != dest.resolve():
        shutil.copytree(SOURCE, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv", "vendor", "dist", "*.pem", "pairing.json"))
    binaries = Path.home() / ".local/bin"
    binaries.mkdir(parents=True, exist_ok=True)
    launcher = binaries / "lan-bridge"
    launcher.write_text('#!/usr/bin/python3\nimport sys\nsys.path.insert(0, ' + repr(str(dest)) + ')\nfrom lanbridge.cli import main\nraise SystemExit(main())\n')
    launcher.chmod(0o755)
    activate_launcher = binaries / "lan-bridge-activate"
    activate_launcher.write_text('#!/usr/bin/python3\nimport os\nos.execv("/usr/bin/python3", ["python3", ' + repr(str(dest / "scripts/install-linux.py")) + ', "--activate"])\n')
    activate_launcher.chmod(0o755)
    applications = Path.home() / ".local/share/applications"
    applications.mkdir(parents=True, exist_ok=True)
    for name, title, entry, terminal in (("lan-bridge", "Lan Bridge", f'"{launcher}" panel', False),
                                         ("lan-bridge-activate", "Activate Lan Bridge", f'"{activate_launcher}"', True)):
        (applications / f"{name}.desktop").write_text(f"[Desktop Entry]\nType=Application\nName={title}\nExec={entry}\nTerminal={str(terminal).lower()}\nIcon=network-workgroup\nCategories=Network;Utility;\n")
    print("Staged Lan Bridge. Existing input and sidebar remain active.")
    print("Activate in the native desktop: ~/.local/bin/lan-bridge-activate")


def activate():
    # Preflight before touching desktop config or stopping a working service.
    command("systemctl", "--user", "show-environment")
    command("hyprctl", "-j", "version")
    old_errors = command("hyprctl", "configerrors").stdout.strip()
    if old_errors and old_errors.lower() != "ok":
        raise SystemExit("Resolve existing Hyprland config errors before activating Lan Bridge: " + old_errors)
    home = Path.home()
    backup = state_dir() / "backups" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, mode=0o700)
    history = []
    input_active = command("systemctl", "--user", "is-active", "--quiet", "lan-mouse.service", check=False).returncode == 0
    input_enabled = command("systemctl", "--user", "is-enabled", "--quiet", "lan-mouse.service", check=False).returncode == 0
    bridge_active = command("systemctl", "--user", "is-active", "--quiet", "lan-bridge.service", check=False).returncode == 0

    def put(path, content, mode=0o644):
        path.parent.mkdir(parents=True, exist_ok=True)
        saved = backup / str(len(history))
        exists = path.exists()
        if exists:
            shutil.copy2(path, saved)
        history.append({"path": str(path), "saved": str(saved) if exists else None})
        path.write_text(content)
        path.chmod(mode)
        atomic_json(backup / "manifest.json", {"files": history, "input_active": input_active, "input_enabled": input_enabled})

    try:
        main = home / ".config/hypr/hyprland.lua"
        content = main.read_text()
        put(home / ".config/hypr/lanbridge.lua", (SOURCE / "integrations/omarchy/lanbridge.lua").read_text())
        updated = add_hyprland_module(content)
        if updated != content:
            put(main, updated)
        command("hyprctl", "reload")
        errors = command("hyprctl", "configerrors").stdout.strip()
        if errors and errors.lower() != "ok":
            raise RuntimeError("Hyprland rejected the viewer rules: " + errors)
        units = home / ".config/systemd/user"
        put(units / "lan-bridge.service", (SOURCE / "integrations/linux/lan-bridge.service").read_text())
        put(units / "lan-mouse.service.d/30-lan-bridge.conf", "[Unit]\nPartOf=lan-bridge.service\n")
        fix = home / ".local/lib/lan-mouse-keyboard-fix.py"
        if not fix.exists():
            put(fix, (SOURCE / "integrations/linux/lan-mouse-keyboard-fix.py").read_text(), 0o755)
        put(units / "lan-mouse.service.d/20-keyboard-correction.conf", "[Service]\nExecStart=\nExecStart=/usr/bin/python3 %h/.local/lib/lan-mouse-keyboard-fix.py\n")
        # Never change shell.json: reuse the existing, working sidebar module path.
        sidebar = home / ".config/omarchy/bar/modules/LanMouseKeyboard.qml"
        if not sidebar.exists():
            raise RuntimeError("Existing Lan Mouse sidebar module missing; integrate the supplied QML using the local Omarchy bar layout")
        command("systemctl", "--user", "daemon-reload")
        command("systemctl", "--user", "disable", "lan-mouse.service")
        if command("systemctl", "--user", "is-failed", "--quiet", "lan-bridge.service", check=False).returncode == 0:
            command("systemctl", "--user", "reset-failed", "lan-bridge.service")
        started = time.time()
        command("systemctl", "--user", "enable", "--now", "lan-bridge.service")
        if bridge_active:
            command("systemctl", "--user", "restart", "lan-bridge.service")
        command("systemctl", "--user", "is-active", "--quiet", "lan-bridge.service")
        command("systemctl", "--user", "is-active", "--quiet", "lan-mouse.service")
        put(sidebar, (SOURCE / "integrations/omarchy/LanMouseKeyboard.qml").read_text())
        put(home / ".local/bin/lan-mouse-sharing", '#!/usr/bin/env bash\nexec "$HOME/.local/bin/lan-bridge" "$@"\n', 0o755)
        atomic_json(state_dir() / "last-install.json", {"backup": str(backup)})
        print("Lan Bridge enabled. Left-click the existing sidebar switch for on/off; right-click for files/settings.")
        print("Checking the Windows feature connection…", flush=True)
        status = wait_for_connection(started)
        if status and status.get("connected"):
            count = len(status.get("displays", []))
            print(f"Windows feature connection: CONNECTED · {count} display(s).")
            if status.get("blocked_workspaces"):
                print("Remote views are waiting for occupied local workspaces to become free.")
        else:
            print("Service enabled; Windows feature connection is still waiting.")
            print("Inspect ~/.local/state/lan-bridge/agent.log and lan-bridge status for details.")
        print(f"Rollback: python3 {SOURCE / 'scripts/rollback-linux.py'}")
    except BaseException:
        command("systemctl", "--user", "disable", "--now", "lan-bridge.service", check=False)
        for item in reversed(history):
            path = Path(item["path"])
            if item["saved"]:
                shutil.copy2(item["saved"], path)
            else:
                path.unlink(missing_ok=True)
        command("hyprctl", "reload", check=False)
        command("hyprctl", "configerrors", check=False)
        command("systemctl", "--user", "daemon-reload", check=False)
        if input_enabled:
            command("systemctl", "--user", "enable", "lan-mouse.service", check=False)
        if input_active:
            command("systemctl", "--user", "start", "lan-mouse.service", check=False)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host")
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    if args.activate:
        activate()
    else:
        stage(args)


if __name__ == "__main__":
    main()
