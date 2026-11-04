#!/usr/bin/env python3
"""Build the pinned GPL Lan Mouse engine with the marked-input capture guard."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lanbridge.config import atomic_json
from lanbridge.engine import UPSTREAM_COMMIT
from lanbridge.input import INJECT_MARKER


def command(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "vendor/lan-mouse")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Build the Windows input engine on Windows")
    args.source.parent.mkdir(parents=True, exist_ok=True)
    if not (args.source / ".git").exists():
        command("git", "-c", "core.autocrlf=false", "clone", "--no-checkout", "https://github.com/feschber/lan-mouse.git", str(args.source))
    command("git", "fetch", "--depth", "1", "origin", UPSTREAM_COMMIT, cwd=args.source)
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.source, text=True).strip() if (args.source / "Cargo.toml").exists() else ""
    if current != UPSTREAM_COMMIT:
        # Checkout refuses unrelated uncommitted edits instead of deleting them.
        command("git", "checkout", "--detach", UPSTREAM_COMMIT, cwd=args.source)
    target = args.source / "input-capture/src/windows/event_thread.rs"
    patch = ROOT / "patches/windows-event-thread.rs"
    metadata = json.loads((ROOT / "patches/upstream.json").read_text())
    original = hashlib.sha256(target.read_text(encoding="utf-8").encode()).hexdigest()
    patched = hashlib.sha256(patch.read_bytes()).hexdigest()
    if original not in (metadata["original_sha256"], patched):
        raise SystemExit("Pinned input hook differs from reviewed source; refusing to overwrite it")
    target.write_bytes(patch.read_bytes())
    command("cargo", "build", "--release", "--locked", "--no-default-features", "--bin", "lan-mouse", cwd=args.source)
    dest = ROOT / "vendor/bin"
    dest.mkdir(parents=True, exist_ok=True)
    exe = dest / "lan-mouse.exe"
    shutil.copy2(args.source / "target/release/lan-mouse.exe", exe)
    atomic_json(dest / "engine-guard.json", {"upstream_commit": UPSTREAM_COMMIT,
        "marker": INJECT_MARKER, "patch_sha256": patched, "sha256": hashlib.sha256(exe.read_bytes()).hexdigest()})
    # Distribute full corresponding modified input-engine source with its binary.
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=args.source).decode().split("\0")
    with zipfile.ZipFile(dest / "corresponding-source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in tracked:
            if name and (args.source / name).is_file():
                archive.write(args.source / name, "lan-mouse/" + name)
        support = [ROOT / "LICENSE", ROOT / "README.md", ROOT / "THIRD_PARTY_NOTICES.md", ROOT / "scripts/build-engine.py"]
        support += list((ROOT / "patches").glob("*")) + list((ROOT / "lanbridge").rglob("*.py"))
        for path in support:
            if path.is_file():
                archive.write(path, "LanBridge-support/" + path.relative_to(ROOT).as_posix())
        archive.writestr("BUILD.txt", "Install Rust stable/MSVC. In lan-mouse run cargo build --release --locked --no-default-features --bin lan-mouse.\nThe reviewed guard is already applied to the supplied source.\n")
    print(f"Guarded Windows input engine: {exe}")


if __name__ == "__main__":
    main()
