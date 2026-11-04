"""Root-confined transfers, checksums, atomic commits and recoverable sync trash."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import time
import uuid
from .wire import CHUNK, ProtocolError

MAX_FILE = 64 * 1024**3
MAX_ENTRIES = 20000
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def relative_name(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ProtocolError("Invalid relative path")
    if "\\" in value or "\x00" in value or any(ord(c) < 32 for c in value):
        raise ProtocolError("Invalid path characters")
    parts = value.split("/")
    if any(p in ("", ".", "..") or p.endswith((" ", ".")) or
           any(c in p for c in ':*?"<>|') or RESERVED.match(p) or
           p.casefold().startswith(".lanbridge-") for p in parts):
        raise ProtocolError("Unsafe or nonportable relative path")
    return str(PurePosixPath(*parts))


def is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def confined(root: Path, name: str) -> Path:
    name = relative_name(name)
    root = root.resolve()
    result = root
    for part in name.split("/"):
        result /= part
        if is_link(result):
            raise ProtocolError("Symbolic links and reparse points are excluded")
    if not result.resolve().is_relative_to(root):
        raise ProtocolError("Path escapes configured root")
    return result


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or is_link(path):
        raise ProtocolError("Expected a regular file")
    result = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            result.update(block)
    return result.hexdigest()


class Store:
    def __init__(self, root: Path):
        if is_link(root):
            raise ProtocolError("Configured Shared/Inbox root must not be a link")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()
        self._hashes = {}

    def manifest(self) -> dict:
        result, folded, hashes = {}, set(), {}
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = [d for d in dirs if not d.casefold().startswith(".lanbridge-")
                       and not is_link(Path(directory) / d)]
            for name in names:
                path = Path(directory) / name
                if is_link(path) or not path.is_file() or name.casefold().startswith(".lanbridge-"):
                    continue
                rel = relative_name(path.relative_to(self.root).as_posix())
                if rel.casefold() in folded:
                    raise ProtocolError("Shared folder has case-colliding names; rename them before sync")
                folded.add(rel.casefold())
                stat = path.stat()
                if stat.st_size > MAX_FILE:
                    raise ProtocolError("Shared file exceeds 64 GiB limit")
                stamp = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
                prior = self._hashes.get(rel)
                checksum = prior[1] if prior and prior[0] == stamp else digest(path)
                after = path.stat()
                if (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino) != stamp:
                    raise ProtocolError("Shared file changed while computing inventory")
                hashes[rel] = (stamp, checksum)
                result[rel] = {"sha256": checksum, "size": stat.st_size}
                if len(result) > MAX_ENTRIES:
                    raise ProtocolError("Shared folder exceeds 20,000 files")
        self._hashes = hashes
        return result

    def archive(self, path: Path):
        if path.exists():
            relative = path.relative_to(self.root)
            trash = self.root / ".lanbridge-trash"
            if is_link(trash):
                raise ProtocolError("Trash folder must not be a link")
            dest = trash / f"{time.time_ns()}-{uuid.uuid4().hex[:8]}" / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, dest)

    def delete(self, name: str, expected: str):
        path = confined(self.root, name)
        if digest(path) != expected:
            raise ProtocolError("File changed since sync inventory; retry required")
        self.archive(path)

    def receive(self, wire, request: dict, *, inbox=False):
        name = relative_name(request["name"])
        size = request["size"]
        wanted = request["sha256"]
        if type(size) is not int or not 0 <= size <= MAX_FILE or not re.fullmatch(r"[0-9a-f]{64}", wanted):
            raise ProtocolError("Invalid transfer metadata")
        final = confined(self.root, name)
        if inbox:
            name = Path(name).name
            final = confined(self.root, name)
            if final.exists():
                p = Path(name)
                name = f"{p.stem} ({uuid.uuid4().hex[:8]}){p.suffix}"
                final = confined(self.root, name)
        stage = self.root / ".lanbridge-staging"
        stage.mkdir(exist_ok=True)
        if is_link(stage):
            raise ProtocolError("Staging folder must not be a link")
        temp = stage / uuid.uuid4().hex
        count, checksum = 0, hashlib.sha256()
        wire.send({"ready": True})
        try:
            with temp.open("xb") as f:
                while count < size:
                    message, block = wire.recv()
                    if message.get("op") != "chunk" or not block or len(block) > CHUNK or count + len(block) > size:
                        raise ProtocolError("Invalid file chunk")
                    if shutil.disk_usage(self.root).free < len(block) + 16 * 1024**2:
                        raise ProtocolError("Destination is low on free space")
                    f.write(block)
                    checksum.update(block)
                    count += len(block)
                f.flush()
                os.fsync(f.fileno())
            done, extra = wire.recv()
            if done.get("op") != "commit" or extra or checksum.hexdigest() != wanted:
                raise ProtocolError("File checksum verification failed")
            final = confined(self.root, name)  # recheck immediately before commit
            if not inbox and digest(final) != request.get("expected"):
                raise ProtocolError("Destination changed during transfer; original preserved")
            final.parent.mkdir(parents=True, exist_ok=True)
            if not inbox:
                self.archive(final)
            elif final.exists():
                raise ProtocolError("Inbox destination became occupied; retry required")
            os.replace(temp, final)
            wire.send({"ok": True, "name": name, "sha256": wanted})
        finally:
            temp.unlink(missing_ok=True)


def send_file(wire, path: Path):
    ready, _ = wire.recv()
    if "error" in ready:
        raise ProtocolError(ready["error"])
    if not ready.get("ready"):
        raise ProtocolError("Receiver refused file")
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            wire.send({"op": "chunk"}, block)
    wire.send({"op": "commit"})
    result, _ = wire.recv()
    if "error" in result:
        raise ProtocolError(result["error"])
    return result


def push(client, scope: str, path: Path, name: str, expected=None):
    checksum = digest(path)
    wire = client.connect("put", scope=scope, name=name, size=path.stat().st_size,
                          sha256=checksum, expected=expected)
    try:
        return send_file(wire, path)
    finally:
        wire.stream.close()


def pull(client, store: Store, name: str, *, expected=None, offer=None, target=None, source=None):
    wire = client.connect("get", scope="offer" if offer else "shared", name=name, offer=offer)
    try:
        metadata, _ = wire.recv()
        if "error" in metadata:
            raise ProtocolError(metadata["error"])
        if source is not None and metadata.get("sha256") != source:
            raise ProtocolError("Source changed since inventory; retry required")
        metadata["expected"] = expected
        if target:
            metadata["name"] = target
        store.receive(wire, metadata, inbox=bool(offer))
    finally:
        wire.stream.close()
