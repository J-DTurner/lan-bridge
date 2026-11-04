"""Explicit user-selected outgoing files. Queue metadata stays on the sender."""
from pathlib import Path
import uuid
from .config import atomic_json, read_json
from .files import digest, relative_name, is_link
from .wire import ProtocolError


class Offers:
    def __init__(self, state: Path):
        self.root = state / "outgoing"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def add(self, path: Path):
        path = path.expanduser().absolute()
        if is_link(path) or not path.is_file():
            raise ValueError("Select a regular file")
        relative_name(path.name)
        ident = uuid.uuid4().hex
        item = {"id": ident, "path": str(path), "name": path.name,
                "size": path.stat().st_size, "sha256": digest(path)}
        atomic_json(self.root / f"{ident}.json", item)
        return ident

    def list(self):
        return [read_json(p) for p in sorted(self.root.glob("*.json"))][:100]

    def get(self, ident):
        import re
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident):
            raise ProtocolError("Invalid offered file ID")
        item = read_json(self.root / f"{ident}.json")
        if item is None:
            raise ProtocolError("File offer expired")
        path = Path(item["path"])
        if is_link(path) or digest(path) != item["sha256"]:
            raise ProtocolError("Offered file changed; select it again")
        return item

    def done(self, ident):
        import re
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident):
            raise ProtocolError("Invalid offered file ID")
        (self.root / f"{ident}.json").unlink(missing_ok=True)

    def cancel_all(self):
        for path in self.root.glob("*.json"):
            path.unlink()
