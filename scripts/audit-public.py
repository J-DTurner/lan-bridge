#!/usr/bin/env python3
"""Scan reachable Git content and metadata without printing sensitive matches."""
from __future__ import annotations
import argparse
import ipaddress
import json
from pathlib import Path
import re
import subprocess

SAFE_IPS = {"0.0.0.0", "127.0.0.1", "::", "::1"}
PRIVATE_SUFFIXES = {".pem", ".key", ".crt", ".cer", ".der", ".pfx", ".p12", ".bundle", ".zip", ".log"}
PRIVATE_FILES = {"pairing.json", "config.json", "session.json", "status.json", "sync-baseline.json",
                 "windows_result.md", "handoff.json", "sha256sums.txt"}
PATTERNS = {
    "certificate/key material": re.compile(r"(?m)^[ \t]*-----BEGIN (?:CERTIFICATE|[A-Z _]*PRIVATE[ _]KEY|OPENSSH PRIVATE KEY)-----[ \t\r]*\n[ \t]*[A-Za-z0-9+/=]{20,}"),
    "access token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:proj-|live-)?[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})\b"),
    "SSH identity": re.compile(r"\bssh-(?:rsa|ed25519) [A-Za-z0-9+/=]{30,}"),
    "device MAC/fingerprint": re.compile(r"\b(?:[A-Fa-f0-9]{2}:){5,}[A-Fa-f0-9]{2}\b"),
    "literal user home": re.compile(r"/home/[A-Za-z0-9_.-]+|[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/][A-Za-z0-9_.-]+"),
}
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6 = re.compile(r"(?<![0-9A-Za-z])(?:[0-9A-Fa-f]{0,4}:){2,}[0-9A-Fa-f]{0,4}(?![0-9A-Za-z])")
EMAIL = re.compile(r"[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|[A-Za-z0-9_.+%-]+@localhost")


def scan_text(text: str, forbidden=()) -> set[str]:
    findings = {kind for kind, pattern in PATTERNS.items() if pattern.search(text)}
    for pattern in (IPV4, IPV6):
        for candidate in pattern.findall(text):
            try:
                address = str(ipaddress.ip_address(candidate))
            except ValueError:
                continue
            if address not in SAFE_IPS:
                findings.add("nonlocal IP address")
    for email in EMAIL.findall(text):
        domain = email.rsplit("@", 1)[1].lower()
        if domain not in {"localhost", "example.invalid", "example.com", "example.org", "example.net"} and domain != "users.noreply.github.com":
            findings.add("email address")
    lowered = text.casefold()
    if any(value and value.casefold() in lowered for value in forbidden):
        findings.add("private deny-list match")
    return findings


def forbidden_path(name):
    path = Path(name)
    lower = path.name.casefold()
    return (path.suffix.casefold() in PRIVATE_SUFFIXES or lower in PRIVATE_FILES or
            lower.startswith(".env") or (lower.startswith("pairing") and lower.endswith(".json")) or
            any(p.casefold() in {"runtime", "outgoing", "backups", "state"} for p in path.parts))


def run_git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def audit(root: Path, forbidden=(), *, snapshot=False):
    errors = set()
    if run_git(root, "status", "--porcelain").strip():
        errors.add("worktree: uncommitted or untracked files")
    commits = run_git(root, "rev-list", "--all").decode().splitlines()
    if not commits:
        errors.add("history: no committed public source")
    if snapshot and len(commits) != 1:
        errors.add("history: publication must start with exactly one sanitized root commit")
    checked = set()
    files = 0
    for commit in commits:
        metadata = run_git(root, "cat-file", "-p", commit).decode("utf-8", "replace")
        for finding in scan_text(metadata, forbidden):
            errors.add(f"commit {commit[:12]}: {finding}")
        entries = run_git(root, "ls-tree", "-rz", commit).split(b"\0")
        for entry in entries:
            if not entry:
                continue
            header, name = entry.split(b"\t", 1)
            mode, kind, sha = header.decode().split()
            path = name.decode("utf-8", "replace")
            if forbidden_path(path):
                errors.add(f"{path}: private/runtime artifact filename")
            for finding in scan_text(path, forbidden):
                errors.add(f"{path}: {finding}")
            if kind != "blob" or mode not in ("100644", "100755"):
                errors.add(f"{path}: nonregular source entry")
                continue
            if sha in checked:
                continue
            checked.add(sha)
            content = run_git(root, "cat-file", "blob", sha)
            files += 1
            if b"\x00" in content:
                errors.add(f"{path}: binary payload requires separate review")
                continue
            for finding in scan_text(content.decode("utf-8", "replace"), forbidden):
                errors.add(f"{path}: {finding}")
    return {"commits_checked": len(commits), "unique_blobs_checked": files,
            "findings": sorted(errors), "passed": not errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--private-rules", type=Path,
                        help="Owner-local JSON {forbidden_literals: [...]} outside the source tree")
    parser.add_argument("--require-snapshot", action="store_true")
    args = parser.parse_args()
    forbidden = []
    if args.private_rules:
        forbidden = json.loads(args.private_rules.read_text())["forbidden_literals"]
    report = audit(args.repository.resolve(), forbidden, snapshot=args.require_snapshot)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
