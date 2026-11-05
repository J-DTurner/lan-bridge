"""Own only our two tiled viewer processes, never other applications."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import time
import logging

log = logging.getLogger(__name__)


def hypr_json(command):
    return json.loads(subprocess.run(["hyprctl", "-j", command], capture_output=True, check=True, timeout=2).stdout)


def occupied(clients, workspace):
    return any(c.get("workspace", {}).get("id") == workspace and
               not c.get("class", "").startswith("local.lanbridge.screen") for c in clients)


class Viewers:
    def __init__(self, config_path: Path, config):
        self.config_path, self.config = Path(config_path).expanduser().resolve(), config
        self.children = {}
        self.last_local = 1
        self.blocked = []
        self.retry_after = {}
        self.display_stamps = {}

    def reconcile(self, displays):
        current = hypr_json("activeworkspace").get("id", 1)
        if current not in self.config["workspaces"] and current > 0:
            self.last_local = current
        clients = hypr_json("clients")
        wanted = {index + 1: int(w) for index, w in enumerate(self.config["workspaces"][:2])
                  if any(d["id"] == index + 1 for d in displays)}
        self.blocked = []
        for monitor, workspace in wanted.items():
            display = next(d for d in displays if d["id"] == monitor)
            stamp = tuple(display.get(k) for k in ("left", "top", "width", "height"))
            child = self.children.get(monitor)
            if child and self.display_stamps.get(monitor) != stamp:
                self._stop(monitor)
                child = None
            self.display_stamps[monitor] = stamp
            if child and child.poll() is None:
                continue
            if child:
                log.warning("Display %s viewer exited with code %s", monitor, child.poll())
                del self.children[monitor]
                self.retry_after[monitor] = time.monotonic() + 5
            if occupied(clients, workspace):
                self.blocked.append(workspace)
                continue
            if time.monotonic() < self.retry_after.get(monitor, 0):
                continue
            self.children[monitor] = subprocess.Popen([
                sys.executable, "-m", "lanbridge", "--config", str(self.config_path),
                "view", "--monitor", str(monitor)],
                cwd=Path(__file__).resolve().parents[1])
            log.info("Display %s viewer started on workspace %s", monitor, workspace)
        for monitor in set(self.children) - set(wanted):
            self._stop(monitor)

    def _stop(self, monitor):
        child = self.children.pop(monitor)
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

    def snapshot(self):
        return {str(monitor): {"pid": getattr(child, "pid", None), "running": child.poll() is None,
                               "workspace": self.config["workspaces"][monitor - 1]}
                for monitor, child in self.children.items()}

    def stop(self):
        if self.children:
            try:
                current = hypr_json("activeworkspace").get("id")
                owned = {self.config["workspaces"][m - 1] for m in self.children}
                if current in owned and not occupied(hypr_json("clients"), current):
                    # Ordinary workspace switch releases focus before viewers close.
                    subprocess.run(["hyprctl", "dispatch", f'hl.dsp.focus({{ workspace = "{self.last_local}" }})'],
                                   capture_output=True, timeout=2, check=True)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        for monitor in list(self.children):
            self._stop(monitor)
