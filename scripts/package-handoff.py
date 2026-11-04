#!/usr/bin/env python3
"""Package committed source/history plus public pairing; never private runtime data."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lanbridge import PROTOCOL, __version__
from lanbridge.cli import main as bridge_main


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True)
    parser.add_argument("--output", type=Path, default=Path.home() / "Downloads/LanBridge-Windows-Handoff")
    args = parser.parse_args()
    if args.output.with_suffix(".zip").exists():
        raise SystemExit("Archive already exists; choose a new output name")
    if git("status", "--porcelain").strip():
        raise SystemExit("Commit the complete, tested source before creating a handoff")
    commit = git("rev-parse", "HEAD").decode().strip()
    files = [p for p in git("ls-files", "-z").decode().split("\0") if p]
    secret = re.compile(rb"-----BEGIN [A-Z _]*PRIVATE[ _]KEY-----\s*[A-Za-z0-9+/=]{30}")
    for name in files:
        path = ROOT / name
        if path.suffix in (".pem", ".key") or path.name in ("config.json", "pairing.json") or secret.search(path.read_bytes()):
            raise SystemExit(f"Private material must not be packaged: {name}")
    if args.output.exists():
        raise SystemExit("Use a new/empty output directory; existing handoff is retained")
    args.output.mkdir(parents=True, mode=0o700)
    for name in files:
        dest = args.output / "source" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, dest)
    subprocess.run(["git", "bundle", "create", str(args.output / "lan-bridge.bundle"), "--all"], cwd=ROOT, check=True)
    if bridge_main(["export-pairing", "--address", args.address, "--output", str(args.output / "pairing.json")]) != 0:
        raise SystemExit("Public pairing export failed")
    metadata = {"project": "Lan Bridge", "version": __version__, "protocol": PROTOCOL, "commit": commit,
                "linux": "staged; native activation required", "windows": "implementation and installer supplied; native build/deployment/tests required",
                "private_keys_included": False, "entrypoint": "source/WINDOWS_AGENT_START_HERE.md"}
    (args.output / "HANDOFF.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (args.output / "START_HERE.txt").write_text("LAN BRIDGE — WINDOWS AGENT HANDOFF\n\nRead source/WINDOWS_AGENT_START_HERE.md first.\nThis folder has the full source, offline Git history and PUBLIC pairing.json.\nClone lan-bridge.bundle into a permanent working directory or use source/.\nDeploy and test on the actual Windows desktop before reporting success.\nLinux activation has been staged, not applied.\n")
    sums = []
    for path in sorted(args.output.rglob("*")):
        if path.is_file():
            sums.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.relative_to(args.output).as_posix())
    (args.output / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    archive = args.output.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip:
        for path in sorted(args.output.rglob("*")):
            if path.is_file():
                zip.write(path, args.output.name + "/" + path.relative_to(args.output).as_posix())
    archive.with_suffix(".zip.sha256").write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n")
    print(f"Handoff created: {archive}\nSource commit: {commit}")


if __name__ == "__main__":
    main()
