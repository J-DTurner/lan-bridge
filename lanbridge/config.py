"""Private configuration, public pairing exports, and atomic state files."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import tempfile


def home_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "LanBridge"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lan-bridge"


def state_dir() -> Path:
    if os.name == "nt":
        return home_dir() / "state"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "lan-bridge"


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def certificate_pem(path: Path) -> str:
    # Only the public certificate leaves this function, never the private key.
    raw = path.read_text(encoding="ascii")
    match = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", raw, re.S)
    if not match:
        raise ValueError("Lan Mouse identity contains no certificate")
    return match.group(0) + "\n"


def fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def normalize_fingerprint(value: str) -> str:
    value = value.replace(":", "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("A SHA-256 certificate fingerprint is required")
    return value


def own_fingerprint(path: Path) -> str:
    return fingerprint(ssl.PEM_cert_to_DER_cert(certificate_pem(path)))


def load(path: Path | None = None) -> dict:
    path = path or home_dir() / "config.json"
    data = read_json(path)
    if not data:
        raise ValueError(f"Run the native installer first; missing {path}")
    data["peer_fingerprint"] = normalize_fingerprint(data["peer_fingerprint"])
    for key in ("identity", "shared", "inbox"):
        data[key] = str(Path(data[key]).expanduser().resolve())
    if Path(data["shared"]) == Path(data["inbox"]):
        raise ValueError("Shared and Inbox must be different folders")
    data.setdefault("port", 4242)
    data.setdefault("clipboard", True)
    data.setdefault("sync", True)
    data.setdefault("audio", False)
    data.setdefault("workspaces", [6, 7])
    data.setdefault("fps", 15)
    data.setdefault("max_width", 1920)
    return data
