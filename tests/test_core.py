import base64
import hashlib
import io
import json
from pathlib import Path
import ssl
import struct
import subprocess
import tempfile
import unittest

from lanbridge import PROTOCOL
from lanbridge.clipboard import Clip, ClipboardLink
from lanbridge.config import atomic_json, certificate_pem, own_fingerprint, fingerprint
from lanbridge.files import Store, relative_name, confined, digest
from lanbridge.input import absolute_point, normalized_point, windows_scancode
from lanbridge.server import Sessions
from lanbridge.sync import plan
from lanbridge.wire import Wire, ProtocolError, MAX_BINARY, server_context, client_context, verify_peer
from lanbridge.workspaces import occupied


class MemoryStream:
    def __init__(self, value=b"", fragment=11):
        self.data = io.BytesIO(value)
        self.output = bytearray()
        self.fragment = fragment

    def recv(self, size):
        return self.data.read(min(size, self.fragment))

    def sendall(self, data):
        self.output.extend(data)


def frames(*messages):
    stream = MemoryStream()
    wire = Wire(stream)
    for message, data in messages:
        wire.send(message, data)
    return bytes(stream.output)


def inventory(**items):
    return {key: {"sha256": value, "size": 1} for key, value in items.items()}


class WireTests(unittest.TestCase):
    def test_fragmented_and_coalesced_frames(self):
        raw = frames(({"op": "one", "unicode": "日"}, b"abc"), ({"op": "two"}, b""))
        wire = Wire(MemoryStream(raw, fragment=1))
        self.assertEqual(wire.recv(), ({"op": "one", "unicode": "日"}, b"abc"))
        self.assertEqual(wire.recv(), ({"op": "two"}, b""))
        with self.assertRaises(EOFError):
            wire.recv()

    def test_oversize_rejected_before_body_read(self):
        with self.assertRaises(ProtocolError):
            Wire(MemoryStream(struct.pack("!II", 2, MAX_BINARY + 1))).recv()

    def test_no_nonobject_or_nonfinite_json(self):
        for value in (b"[]", b'{"x":NaN}', b'{"x":Infinity}'):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                Wire(MemoryStream(struct.pack("!II", len(value), 0) + value)).recv()

    def test_authorization_revokes_open_transfer(self):
        wire = Wire(MemoryStream())
        wire.authorize = lambda: (_ for _ in ()).throw(ProtocolError("revoked"))
        with self.assertRaises(ProtocolError):
            wire.send({"op": "chunk"}, b"private")
        self.assertEqual(wire.stream.output, b"")


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "root"
        self.store = Store(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_portable_paths(self):
        for name in ("../secret", "/abs", "a//b", "a/./b", "C:/foo", "a\\b", "aux.txt", "x/COM1", "x.", ".lanbridge-trash/a", "x\x00y"):
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                relative_name(name)
        self.assertEqual(relative_name("folder/画像.png"), "folder/画像.png")

    def test_symlink_escape_blocked(self):
        try:
            (self.root / "link").symlink_to(Path(self.temp.name), target_is_directory=True)
        except OSError:
            self.skipTest("Native symlink privilege unavailable")
        with self.assertRaises(ProtocolError):
            confined(self.root, "link/private")

    def test_symlink_root_cannot_enroll_another_folder(self):
        linked = Path(self.temp.name) / "linked-root"
        try:
            linked.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("Native symlink privilege unavailable")
        with self.assertRaises(ProtocolError):
            Store(linked)

    def test_inventory_hash_cache_detects_equal_size_edit(self):
        path = self.root / "file"
        path.write_bytes(b"old")
        before = self.store.manifest()["file"]["sha256"]
        path.write_bytes(b"new")
        after = self.store.manifest()["file"]["sha256"]
        self.assertNotEqual(before, after)
        self.assertEqual(after, hashlib.sha256(b"new").hexdigest())

    def receive(self, content, *, expected=None, checksum=None, inbox=False):
        wanted = checksum or hashlib.sha256(content).hexdigest()
        request = {"name": "nested/file.txt", "size": len(content), "sha256": wanted, "expected": expected}
        blocks = [({"op": "chunk"}, content)] if content else []
        stream = MemoryStream(frames(*blocks, ({"op": "commit"}, b"")))
        self.store.receive(Wire(stream), request, inbox=inbox)
        return Wire(MemoryStream(bytes(stream.output)))

    def test_atomic_checksum_verified_upload(self):
        self.receive(b"first")
        self.assertEqual((self.root / "nested/file.txt").read_bytes(), b"first")
        old = digest(self.root / "nested/file.txt")
        self.receive(b"second", expected=old)
        self.assertEqual((self.root / "nested/file.txt").read_bytes(), b"second")
        backups = list((self.root / ".lanbridge-trash").rglob("file.txt"))
        self.assertEqual([p.read_bytes() for p in backups], [b"first"])

    def test_bad_checksum_never_replaces_original(self):
        self.receive(b"first")
        with self.assertRaises(ProtocolError):
            self.receive(b"changed", expected=digest(self.root / "nested/file.txt"), checksum="0" * 64)
        self.assertEqual((self.root / "nested/file.txt").read_bytes(), b"first")
        self.assertEqual(list((self.root / ".lanbridge-staging").iterdir()), [])

    def test_concurrent_destination_edit_preserved(self):
        self.receive(b"unsaved edit")
        with self.assertRaises(ProtocolError):
            self.receive(b"remote overwrite", expected="0" * 64)
        self.assertEqual((self.root / "nested/file.txt").read_bytes(), b"unsaved edit")

    def test_zero_length_and_inbox_collisions(self):
        self.receive(b"", inbox=True)
        self.receive(b"two", inbox=True)
        self.assertEqual(len(list(self.root.glob("*.txt"))), 2)

    def test_deletion_recoverable_and_inventory_excludes_internal(self):
        self.receive(b"saved")
        self.store.delete("nested/file.txt", digest(self.root / "nested/file.txt"))
        self.assertEqual(self.store.manifest(), {})
        self.assertEqual(next((self.root / ".lanbridge-trash").rglob("file.txt")).read_bytes(), b"saved")

    def test_case_collision_is_not_silently_merged(self):
        import os
        if os.name == "nt":
            self.skipTest("NTFS cannot create this Linux-only collision; cross-peer collisions are tested separately")
        (self.root / "A.txt").write_text("one")
        (self.root / "a.txt").write_text("two")
        with self.assertRaises(ProtocolError):
            self.store.manifest()


class SyncTests(unittest.TestCase):
    def kinds(self, left, right, base):
        return [a.kind for a in plan(left, right, base)]

    def test_initial_both_directions_and_conflict(self):
        self.assertEqual(self.kinds(inventory(a="L"), inventory(b="R"), {}), ["push", "pull"])
        self.assertEqual(self.kinds(inventory(a="L"), inventory(a="R"), {}), ["conflict"])

    def test_edits_deletions_and_concurrent_edit(self):
        cases = [("new", "old", "push"), ("old", "new", "pull"),
                 (None, "old", "delete_remote"), ("old", None, "delete_local"),
                 ("new", "other", "conflict"), ("new", None, "conflict")]
        for left, right, expected in cases:
            with self.subTest(left=left, right=right):
                l = inventory(a=left) if left else {}
                r = inventory(a=right) if right else {}
                self.assertEqual(self.kinds(l, r, {"a": "old"}), [expected])

    def test_cross_peer_case_collision_blocked(self):
        with self.assertRaises(ProtocolError):
            plan(inventory(A="1"), inventory(a="2"), {})


class ClipboardTests(unittest.TestCase):
    def test_unicode_png_and_tamper(self):
        for clip in (Clip("text/plain;charset=utf-8", "Hello 👋\n".encode()), Clip("image/png", b"\x89PNG\r\n")):
            self.assertEqual(Clip.parse(clip.message()), clip)
            message = clip.message()
            message["data"] = base64.b64encode(b"tampered").decode()
            with self.assertRaises(ProtocolError):
                Clip.parse(message)

    def test_feedback_is_suppressed(self):
        class Adapter:
            value = Clip("text/plain;charset=utf-8", b"one")
            writes = 0
            def read(self): return self.value
            def write(self, value): self.value = value; self.writes += 1
        adapter = Adapter()
        link = ClipboardLink(adapter)
        original = link.changed()
        link.apply(original)
        self.assertEqual(adapter.writes, 0)
        remote = Clip(original.mime, b"two")
        link.apply(remote)
        self.assertIsNone(link.changed())
        self.assertEqual(adapter.writes, 1)


class InputTests(unittest.TestCase):
    def test_letterboxing_and_hidpi_normalization(self):
        self.assertIsNone(normalized_point(50, 5, 100, 100, 1920, 1080))
        self.assertEqual(normalized_point(50, 50, 100, 100, 1920, 1080), (0.5, 0.5))
        self.assertEqual(normalized_point(100, 50, 200, 100, 3840, 2160), (0.5, 0.5))

    def test_negative_monitor_origin_and_rightmost_pixel(self):
        virtual = {"left": -1920, "top": -200, "width": 4480, "height": 1640}
        left = {"left": -1920, "top": 0, "width": 1920, "height": 1080}
        right = {"left": 0, "top": -200, "width": 2560, "height": 1440}
        self.assertEqual(absolute_point(left, virtual, 0, 0)[0], 0)
        self.assertEqual(absolute_point(right, virtual, 1, 0), (65535, 0))
        for value in (float("nan"), -1, 2, None):
            with self.assertRaises(ProtocolError):
                absolute_point(left, virtual, value, 0)

    def test_modifiers_extended_keys(self):
        self.assertEqual(windows_scancode(56), 56)
        self.assertEqual(windows_scancode(125), 0xE05B)
        self.assertEqual(windows_scancode(100), 0xE038)
        self.assertEqual(windows_scancode(103), 0xE048)
        self.assertIsNone(windows_scancode(999))

    def test_does_not_take_other_apps_workspaces(self):
        self.assertTrue(occupied([{"workspace": {"id": 6}, "class": "steam"}], 6))
        self.assertFalse(occupied([{"workspace": {"id": 6}, "class": "local.lanbridge.screen1"}], 6))


class SessionTests(unittest.TestCase):
    def test_lease_renewal_expiry_and_revoke(self):
        now = [0]
        sessions = Sessions(clock=lambda: now[0])
        token = sessions.open()
        sessions.check(token)
        now[0] = 19
        sessions.check(token, renew=True)
        now[0] = 21
        sessions.check(token)
        sessions.close()
        with self.assertRaises(ProtocolError): sessions.check(token)
        token = sessions.open()
        now[0] = 42
        with self.assertRaises(ProtocolError): sessions.check(token)


class TLSMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for name in ("client", "server", "stranger"):
            key, cert = cls.root / f"{name}.key", cls.root / f"{name}.crt"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                            "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", f"/CN={name}",
                            "-addext", "basicConstraints=critical,CA:FALSE"], check=True, capture_output=True)
            (cls.root / f"{name}.pem").write_bytes(cert.read_bytes() + key.read_bytes())

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def handshake(self, client_name="client"):
        client = client_context(str(self.root / f"{client_name}.pem"))
        server = server_context(str(self.root / "server.pem"), certificate_pem(self.root / "client.pem"))
        ci, co, si, so = (ssl.MemoryBIO() for _ in range(4))
        c = client.wrap_bio(ci, co, server_side=False, server_hostname="lan-bridge")
        s = server.wrap_bio(si, so, server_side=True)
        done = set()
        for _ in range(100):
            for name, obj in (("c", c), ("s", s)):
                if name not in done:
                    try: obj.do_handshake(); done.add(name)
                    except ssl.SSLWantReadError: pass
            data = co.read()
            if data: si.write(data)
            data = so.read()
            if data: ci.write(data)
            if len(done) == 2:
                return c, s, ci, co, si, so
        self.fail("In-memory TLS handshake did not finish")

    def test_real_mutual_tls_and_pins(self):
        c, s, ci, co, si, so = self.handshake()
        verify_peer(c, own_fingerprint(self.root / "server.pem"))
        verify_peer(s, own_fingerprint(self.root / "client.pem"))
        c.write(b"private application data")
        encrypted = co.read()
        self.assertNotIn(b"private application data", encrypted)
        si.write(encrypted)
        self.assertEqual(s.read(), b"private application data")
        with self.assertRaises(ssl.SSLError): verify_peer(c, "0" * 64)

    def test_unapproved_client_is_rejected(self):
        with self.assertRaises(ssl.SSLError): self.handshake("stranger")

    def test_public_export_has_no_key(self):
        public = certificate_pem(self.root / "client.pem")
        self.assertIn("BEGIN CERTIFICATE", public)
        self.assertNotIn("PRIVATE", public)
        self.assertEqual(len(own_fingerprint(self.root / "client.pem")), 64)

    def test_lan_mouse_private_key_envelope_is_normalized_without_changing_identity(self):
        original = (self.root / "client.pem").read_text()
        custom = original.replace("BEGIN PRIVATE KEY", "BEGIN PRIVATE_KEY").replace("END PRIVATE KEY", "END PRIVATE_KEY")
        path = self.root / "lan-mouse.pem"
        path.write_text(custom)
        context = client_context(str(path))
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(path.read_text(), custom)
        self.assertEqual(own_fingerprint(path), own_fingerprint(self.root / "client.pem"))


if __name__ == "__main__":
    unittest.main()
