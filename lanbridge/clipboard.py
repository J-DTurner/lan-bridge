"""Clipboard snapshots with content hashes to prevent feedback loops."""
from __future__ import annotations
import base64
from dataclasses import dataclass
import hashlib
from .wire import ProtocolError

MAX_CLIPBOARD = 4 * 1024**2
MIMES = ("text/plain;charset=utf-8", "image/png")


@dataclass(frozen=True)
class Clip:
    mime: str
    data: bytes

    @property
    def key(self):
        return hashlib.sha256(self.mime.encode() + b"\x00" + self.data).hexdigest()

    def message(self):
        if self.mime not in MIMES or len(self.data) > MAX_CLIPBOARD:
            raise ProtocolError("Unsupported clipboard format or size")
        return {"mime": self.mime, "data": base64.b64encode(self.data).decode("ascii"), "hash": self.key}

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or value.get("mime") not in MIMES:
            raise ProtocolError("Invalid clipboard format")
        encoded = value.get("data", "")
        if not isinstance(encoded, str) or len(encoded) > (MAX_CLIPBOARD + 2) // 3 * 4:
            raise ProtocolError("Clipboard exceeds limit")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ProtocolError("Invalid clipboard encoding") from exc
        if len(data) > MAX_CLIPBOARD:
            raise ProtocolError("Clipboard exceeds limit")
        clip = cls(value["mime"], data)
        if clip.key != value.get("hash"):
            raise ProtocolError("Clipboard checksum mismatch")
        return clip


class ClipboardLink:
    def __init__(self, adapter):
        self.adapter = adapter
        self.seen = None

    def changed(self):
        clip = self.adapter.read()
        if clip is None or clip.key == self.seen:
            return None
        self.seen = clip.key
        return clip

    def apply(self, clip):
        if clip.key != self.seen:
            self.adapter.write(clip)
            self.seen = clip.key
