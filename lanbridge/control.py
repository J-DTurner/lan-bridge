"""Native lifecycle control used by the single sidebar switch and panels."""
from __future__ import annotations
import contextlib
import json
import os
from pathlib import Path
import subprocess
import time
from .config import state_dir, read_json


def systemd(*args, check=True):
    return subprocess.run(["systemctl", "--user", *args], check=check,
                          capture_output=True, text=True, timeout=25)


def active():
    if os.name == "nt":
        status = read_json(state_dir() / "status.json", {})
        return status.get("running", False) and time.time() - status.get("updated", 0) < 8
    return systemd("is-active", "--quiet", "lan-bridge.service", check=False).returncode == 0


def change(mode):
    if mode == "toggle":
        mode = "off" if active() else "on"
    if os.name == "nt":
        if mode == "off":
            (state_dir() / "stop.request").touch()
            subprocess.run(["schtasks", "/Change", "/TN", "Lan Bridge", "/Disable"], check=True, capture_output=True)
        else:
            (state_dir() / "stop.request").unlink(missing_ok=True)
            subprocess.run(["schtasks", "/Change", "/TN", "Lan Bridge", "/Enable"], check=True, capture_output=True)
            subprocess.run(["schtasks", "/Run", "/TN", "Lan Bridge"], check=True, capture_output=True)
        return
    import fcntl
    if not (Path.home() / ".config/systemd/user/lan-bridge.service").is_file():
        raise RuntimeError("Lan Bridge is staged. Run ~/.local/bin/lan-bridge-activate in the native desktop first")
    root = state_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "control.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if mode == "off":
            systemd("disable", "--now", "lan-bridge.service")
            systemd("disable", "--now", "lan-mouse.service")
            subprocess.run(["pkill", "-TERM", "-u", str(os.getuid()), "-x", "lan-mouse"], check=False)
        else:
            if systemd("is-active", "--quiet", "lan-mouse.service", check=False).returncode != 0:
                subprocess.run(["pkill", "-TERM", "-u", str(os.getuid()), "-x", "lan-mouse"], check=False)
            fix = Path.home() / ".local/lib/lan-mouse-keyboard-fix.py"
            subprocess.run(["python3", str(fix), "--self-test"], check=True, capture_output=True, timeout=5)
            subprocess.run(["python3", str(fix), "--transport-test"], check=True, capture_output=True, timeout=5)
            systemd("daemon-reload")
            for service in ("lan-mouse.service", "lan-bridge.service"):
                if systemd("is-failed", "--quiet", service, check=False).returncode == 0:
                    systemd("reset-failed", service)
            # Keep one login owner; bridge Wants=lan-mouse starts the input engine.
            systemd("disable", "lan-mouse.service")
            systemd("enable", "--now", "lan-bridge.service")
            systemd("is-active", "--quiet", "lan-mouse.service")


def bar_status():
    running = active()
    status = read_json(state_dir() / "status.json", {})
    connected = running and status.get("connected", False) and time.time() - status.get("updated", 0) < 8
    tip = "Lan Bridge: OFF · Click to enable sharing"
    if running:
        tip = "Lan Bridge: ON · Windows connected · Workspaces 6/7" if connected else "Lan Bridge: ON · Waiting for Windows companion"
    return {"enabled": running, "connected": connected, "busy": False,
            "tooltip": tip + " · Right-click for files and settings", "class": "active" if running else "inactive"}
