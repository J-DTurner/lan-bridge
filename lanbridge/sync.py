"""A deterministic three-way sync plan; concurrent edits keep both versions."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import uuid
from .config import read_json, atomic_json
from .files import Store, confined, digest, push, pull
from .wire import ProtocolError


@dataclass(frozen=True)
class Action:
    kind: str
    name: str
    local: str | None
    remote: str | None


def plan(local: dict, remote: dict, baseline: dict) -> list[Action]:
    result = []
    names = sorted(set(local) | set(remote) | set(baseline))
    # NTFS is case-insensitive. Refuse ambiguous cross-machine merges too.
    folded = {}
    for name in names:
        other = folded.setdefault(name.casefold(), name)
        if other != name:
            raise ProtocolError("Case-colliding paths across machines; rename before sync")
    for name in names:
        left = local.get(name, {}).get("sha256")
        right = remote.get(name, {}).get("sha256")
        if left == right:
            continue
        old = baseline.get(name)
        if name not in baseline:
            kind = "pull" if left is None else "push" if right is None else "conflict"
        elif left == old:
            kind = "delete_local" if right is None else "pull"
        elif right == old:
            kind = "delete_remote" if left is None else "push"
        else:
            kind = "conflict"
        result.append(Action(kind, name, left, right))
    return result


class Synchronizer:
    def __init__(self, client, root: Path, baseline: Path):
        self.client, self.store, self.baseline = client, Store(root), baseline

    def run(self):
        local = self.store.manifest()
        remote, _ = self.client.call("manifest")
        remote = remote["files"]
        baseline = read_json(self.baseline, {})
        for action in plan(local, remote, baseline):
            name, kind = action.name, action.kind
            path = confined(self.store.root, name)
            if kind == "push":
                if digest(path) != action.local:
                    raise ProtocolError("Local file changed; rescan required")
                push(self.client, "shared", path, name, action.remote)
            elif kind == "pull":
                pull(self.client, self.store, name, expected=action.local)
            elif kind == "delete_local":
                self.store.delete(name, action.local)
            elif kind == "delete_remote":
                self.client.call("delete", name=name, expected=action.remote)
            else:
                # Concurrent edit/deletion: never discard the surviving version.
                if action.local is None:
                    pull(self.client, self.store, name, expected=None)
                elif action.remote is None:
                    push(self.client, "shared", path, name, None)
                else:
                    p = Path(name)
                    conflict = str(p.with_name(f"{p.stem}.conflict-windows-{uuid.uuid4().hex[:8]}{p.suffix}")).replace("\\", "/")
                    pull(self.client, self.store, name, target=conflict, source=action.remote)
                    push(self.client, "shared", confined(self.store.root, conflict), conflict, None)
                    if digest(path) != action.local:
                        raise ProtocolError("Local edit during conflict resolution; retry required")
                    push(self.client, "shared", path, name, action.remote)
        # Commit only a converged baseline. A failed run never legitimizes partial
        # state as a new common ancestor.
        after = self.store.manifest()
        there, _ = self.client.call("manifest")
        if after != there["files"]:
            raise ProtocolError("Folders changed during sync; next pass will retry")
        atomic_json(self.baseline, {n: item["sha256"] for n, item in after.items()})
