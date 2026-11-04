#!/usr/bin/env python3
"""Validate existing identities and prepare one Windows companion configuration."""
import argparse
import datetime
import os
from pathlib import Path
import re
import shutil
import ssl
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lanbridge import PROTOCOL
from lanbridge.config import home_dir, state_dir, read_json, atomic_json, own_fingerprint, normalize_fingerprint, fingerprint
from lanbridge.engine import guard_verified


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairing", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Configure the Windows companion on Windows")
    pair = read_json(args.pairing)
    if pair.get("protocol") != PROTOCOL:
        raise SystemExit("Pairing export has an incompatible protocol")
    linux_pin = normalize_fingerprint(pair["linux_fingerprint"])
    if fingerprint(ssl.PEM_cert_to_DER_cert(pair["linux_certificate"])) != linux_pin:
        raise SystemExit("Linux public certificate fingerprint does not match pairing export")
    identity = home_dir().parent / "lan-mouse/lan-mouse.pem"
    if not identity.exists():
        raise SystemExit("Run Lan Mouse once as the logged-in user; preserve the already-paired identity")
    if own_fingerprint(identity) != normalize_fingerprint(pair["expected_windows_fingerprint"]):
        raise SystemExit("This is not the Windows identity already approved on Linux; do not replace either private key")
    old_config = read_json(home_dir() / "config.json", {})
    config = {"identity": str(identity), "host": pair["linux_address"], "port": pair["port"],
              "listen": "0.0.0.0", "peer_fingerprint": linux_pin,
              "peer_certificate": pair["linux_certificate"],
              "shared": old_config.get("shared", str(Path.home() / "Lan Bridge Shared")),
              "inbox": old_config.get("inbox", str(Path.home() / "Downloads/Lan Bridge Inbox")),
              "clipboard": old_config.get("clipboard", True), "sync": old_config.get("sync", True),
              "audio": old_config.get("audio", True), "workspaces": [6, 7], "fps": 15, "max_width": 1920,
              "engine": str(ROOT / "vendor/bin/lan-mouse.exe"),
              "engine_guard": str(ROOT / "vendor/bin/engine-guard.json")}
    if not guard_verified(config):
        raise SystemExit("Build the guarded Windows input engine first: python scripts/build-engine.py")
    # Preserve the user's existing TOML, including all clients and trust entries.
    toml_path = identity.parent / "config.toml"
    text = toml_path.read_text(encoding="utf-8-sig") if toml_path.exists() else ""
    doc = tomllib.loads(text)
    colon_pin = ":".join(linux_pin[i:i + 2] for i in range(0, 64, 2))
    if colon_pin not in doc.get("authorized_fingerprints", {}):
        header = re.search(r"(?m)^\[authorized_fingerprints\][ \t]*\r?$", text)
        line = f'"{colon_pin}" = "Linux laptop"\n'
        if header:
            text = text[:header.end()] + "\n" + line + text[header.end():]
        elif "authorized_fingerprints" not in doc:
            text = text.rstrip() + "\n\n[authorized_fingerprints]\n" + line
        else:
            raise SystemExit("Authorized fingerprints use an inline TOML table; add the Linux fingerprint without overwriting existing entries")
        tomllib.loads(text)
        backups = state_dir() / "backups" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backups.mkdir(parents=True, exist_ok=True)
        if toml_path.exists():
            shutil.copy2(toml_path, backups / "lan-mouse-config.toml")
        toml_path.write_text(text, encoding="utf-8")
    if (home_dir() / "config.json").exists():
        backup = state_dir() / "backups" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(home_dir() / "config.json", backup / "config.json")
    atomic_json(home_dir() / "config.json", config)
    print("Windows config ready; existing Lan Mouse certificate and clients preserved")


if __name__ == "__main__":
    main()
