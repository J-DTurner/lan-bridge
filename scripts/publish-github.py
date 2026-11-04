#!/usr/bin/env python3
"""Publish an audited source snapshot using the user's native GitHub CLI login."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args, capture=False, check=True):
    return subprocess.run(args, cwd=ROOT, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


def git(*args):
    return run("git", "-c", "core.hooksPath=/dev/null", *args, capture=True).stdout.strip()


def api(path):
    response = run("gh", "api", "--hostname", "github.com", path, capture=True, check=False)
    if response.returncode:
        if "HTTP 404" in response.stderr:
            return None
        raise RuntimeError("GitHub API request failed: " + response.stderr.strip())
    return json.loads(response.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--name", default="lan-bridge")
    parser.add_argument("--private-rules", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9-]+", args.owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", args.name):
        parser.error("Invalid GitHub owner or repository name")
    spec = importlib.util.spec_from_file_location("publication_audit", ROOT / "scripts/audit-public.py")
    auditor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auditor)
    forbidden = json.loads(args.private_rules.read_text())["forbidden_literals"] if args.private_rules else []
    report = auditor.audit(ROOT, forbidden, snapshot=True)
    print(json.dumps(report, indent=2), flush=True)
    if not report["passed"]:
        raise SystemExit("Privacy audit failed; nothing has been published")
    commit = git("rev-parse", "HEAD")
    if git("branch", "--show-current") != "main":
        raise SystemExit("Publish the audited main branch only")
    if args.check_only:
        print("Audited public snapshot is ready; no network actions performed")
        return
    if run("gh", "auth", "status", "--hostname", "github.com", capture=True, check=False).returncode:
        print("GitHub CLI sign-in is required. Complete the browser sign-in yourself.", flush=True)
        run("gh", "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web", "--scopes", "workflow")
    profile = api("user")
    if profile["login"].casefold() != args.owner.casefold():
        raise SystemExit("GitHub CLI is signed into a different account; nothing published")
    destination = f"{args.owner}/{args.name}"
    repo = api(f"repos/{destination}")
    if repo is not None:
        if repo["private"]:
            raise SystemExit("An existing private repository has this name; its visibility was not changed")
        branches = api(f"repos/{destination}/branches?per_page=100") or []
        if any(branch["name"] != "main" or branch["commit"]["sha"] != commit for branch in branches):
            raise SystemExit("Existing repository has other history; refusing to publish over it")
        if api(f"repos/{destination}/tags?per_page=100"):
            raise SystemExit("Existing repository has tags that require a separate history audit")
    else:
        # No content has left the computer until all local audit checks have passed.
        run("gh", "repo", "create", destination, "--public", "--description",
            "Integrated Linux/Windows input sharing, clipboard, files, sync and remote workspaces")
    url = f"https://github.com/{destination}"
    remotes = git("remote").splitlines()
    if "origin" in remotes:
        if git("remote", "get-url", "origin").removesuffix(".git") != url:
            raise SystemExit("Existing origin is different; refusing to replace it")
    else:
        git("remote", "add", "origin", url + ".git")
    # Credential material is exchanged only between gh and Git, never printed.
    # Push one explicit branch: never --all, --mirror, tags or private history.
    run("git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
        "-c", "credential.https://github.com.helper=",
        "-c", "credential.https://github.com.helper=!gh auth git-credential",
        "push", "--set-upstream", "origin", "main:main")
    remote = api(f"repos/{destination}")
    head = api(f"repos/{destination}/git/ref/heads/main")
    if remote["private"] or head["object"]["sha"] != commit:
        raise SystemExit("Post-publication verification failed; inspect GitHub before continuing")
    tree = api(f"repos/{destination}/git/trees/{commit}?recursive=1")
    local = {}
    for row in git("ls-tree", "-r", "HEAD").splitlines():
        header, name = row.split("\t", 1)
        mode, kind, sha = header.split()
        local[name] = (mode, kind, sha)
    remote_tree = {item["path"]: (item["mode"], item["type"], item["sha"])
                   for item in tree["tree"] if item["type"] != "tree"}
    if tree.get("truncated") or local != remote_tree:
        raise SystemExit("Remote source verification failed")
    print(f"Published and verified public source: {url}\nCommit: {commit}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
