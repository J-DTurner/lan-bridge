"""Bounded frames over certificate-pinned TLS; no pickle or remote shell."""
from __future__ import annotations
import json
import socket
import ssl
import struct
import threading
import os
import tempfile
import select
from . import PROTOCOL
from .config import certificate_pem, fingerprint, home_dir
from pathlib import Path

MAX_JSON = 8 * 1024 * 1024
MAX_BINARY = 12 * 1024 * 1024
CHUNK = 256 * 1024


class ProtocolError(ValueError):
    pass


def read_exact(stream, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        block = stream.recv(size - len(result))
        if not block:
            raise EOFError("Peer disconnected")
        result.extend(block)
    return bytes(result)


class Wire:
    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()
        self.authorize = None

    def send(self, message: dict, payload: bytes = b""):
        if self.authorize:
            self.authorize()
        data = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(data) > MAX_JSON or len(payload) > MAX_BINARY:
            raise ProtocolError("Frame exceeds limit")
        with self.lock:
            self.stream.sendall(struct.pack("!II", len(data), len(payload)) + data + payload)

    def readable(self, timeout=0):
        if getattr(self.stream, "pending", lambda: 0)():
            return True
        return bool(select.select([self.stream], [], [], timeout)[0])

    def recv(self) -> tuple[dict, bytes]:
        if self.authorize:
            self.authorize()
        header, binary = struct.unpack("!II", read_exact(self.stream, 8))
        if not 2 <= header <= MAX_JSON or binary > MAX_BINARY:
            raise ProtocolError("Invalid frame length")
        try:
            message = json.loads(read_exact(self.stream, header), parse_constant=lambda x: (_ for _ in ()).throw(ProtocolError("Non-finite number")))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("Invalid JSON") from exc
        if not isinstance(message, dict):
            raise ProtocolError("Message must be an object")
        payload = read_exact(self.stream, binary)
        if self.authorize:
            self.authorize()
        return message, payload


def load_identity(ctx, identity):
    # webrtc-dtls 0.12 serializes PKCS#8 as PRIVATE_KEY (underscore).
    # OpenSSL requires PRIVATE KEY. Preserve the existing identity verbatim;
    # normalize only the PEM envelope in a private, short-lived temporary file.
    raw = Path(identity).read_text(encoding="ascii")
    if "-----BEGIN PRIVATE_KEY-----" not in raw:
        ctx.load_cert_chain(identity)
        return
    private = home_dir()
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".tls-", dir=private) as directory:
        path = Path(directory) / "identity.pem"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(raw.replace("BEGIN PRIVATE_KEY", "BEGIN PRIVATE KEY").replace("END PRIVATE_KEY", "END PRIVATE KEY"))
        ctx.load_cert_chain(path)


def client_context(identity: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    # Self-signed Lan Mouse certificates: verify exact SHA256 pin immediately
    # after handshake and BEFORE any application data is sent.
    ctx.verify_mode = ssl.CERT_NONE
    load_identity(ctx, identity)
    return ctx


def server_context(identity: str, peer_certificate: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    load_identity(ctx, identity)
    ctx.load_verify_locations(cadata=peer_certificate)
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def verify_peer(stream, expected: str):
    import hmac
    if not hmac.compare_digest(fingerprint(stream.getpeercert(binary_form=True)), expected):
        raise ssl.SSLError("Peer certificate does not match the approved Lan Mouse identity")


class Client:
    def __init__(self, config: dict):
        self.config = config
        self.context = client_context(config["identity"])
        self.session = None

    def connect(self, operation: str, **kwargs) -> Wire:
        raw = socket.create_connection((self.config["host"], self.config["port"]), timeout=5)
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock = None
        try:
            sock = self.context.wrap_socket(raw, server_hostname="lan-bridge")
            sock.settimeout(120 if operation in ("manifest", "put", "get") else 12)
            verify_peer(sock, self.config["peer_fingerprint"])
            wire = Wire(sock)
            wire.send({"protocol": PROTOCOL, "op": operation, "session": self.session, **kwargs})
            return wire
        except BaseException:
            (sock if sock is not None else raw).close()
            raise

    def call(self, operation: str, **kwargs):
        wire = self.connect(operation, **kwargs)
        try:
            message, payload = wire.recv()
            if "error" in message:
                raise ProtocolError(message["error"])
            return message, payload
        finally:
            wire.stream.close()
