"""The existing input engine stays an internal, supervised dependency."""
from __future__ import annotations
import hashlib
from functools import lru_cache
from pathlib import Path
import subprocess
from .config import read_json
from .input import INJECT_MARKER

UPSTREAM_COMMIT = "0d2190e787db9e482e17d4c16fb7c00ef4841bcb"


def guard_verified(config):
    path = Path(config.get("engine", ""))
    manifest = read_json(Path(config.get("engine_guard", "missing-guard.json")), {})
    if not path.is_file() or manifest.get("upstream_commit") != UPSTREAM_COMMIT or manifest.get("marker") != INJECT_MARKER:
        return False
    stat = path.stat()
    checksum = binary_digest(str(path), stat.st_size, stat.st_mtime_ns)
    return checksum == manifest.get("sha256")


@lru_cache(maxsize=8)
def binary_digest(path, size, mtime):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Engine:
    def __init__(self, config):
        self.config, self.child = config, None

    def start(self):
        if not self.config.get("engine"):
            return  # view-only development mode; existing engine is untouched
        if not guard_verified(self.config):
            raise RuntimeError("Build the pinned Lan Mouse input guard before starting the Windows companion")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.child = subprocess.Popen([self.config["engine"], "daemon"], creationflags=flags)

    def check(self):
        if self.child is not None and self.child.poll() is not None:
            raise RuntimeError("Lan Mouse input engine exited; companion stopped")

    def stop(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
