"""Use the real file handlers and framing over in-memory fragmented streams."""
import hashlib
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from lanbridge.files import Store, push, pull
from lanbridge.server import Server
from lanbridge.sync import Synchronizer
from lanbridge.wire import Wire, ProtocolError


class Endpoint:
    def __init__(self):
        self.incoming = queue.Queue()
        self.buffer = bytearray()
        self.peer = None
        self.closed = False

    def sendall(self, value):
        if self.closed:
            raise BrokenPipeError()
        # Multiple protocol frames may be coalesced; recv also fragments them.
        self.peer.incoming.put(bytes(value))

    def recv(self, size):
        while not self.buffer:
            value = self.incoming.get(timeout=3)
            if value is None:
                return b""
            self.buffer.extend(value)
        count = min(size, len(self.buffer), 137)
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result

    def close(self):
        if not self.closed:
            self.closed = True
            self.peer.incoming.put(None)


class InMemoryPeer:
    def __init__(self, shared, inbox):
        self.server = Server.__new__(Server)
        self.server.shared = Store(shared)
        self.server.inbox = Store(inbox)
        self.server.config = {"sync": True}
        self.workers = []

    def call(self, op, **kwargs):
        if op == "manifest":
            return {"files": self.server.shared.manifest()}, b""
        if op == "delete":
            self.server.shared.delete(kwargs["name"], kwargs["expected"])
            return {"ok": True}, b""
        raise AssertionError(op)

    def connect(self, op, **kwargs):
        local, remote = Endpoint(), Endpoint()
        local.peer, remote.peer = remote, local
        server_wire = Wire(remote)
        def worker():
            try:
                self.server.handle_file(server_wire, {"op": op, **kwargs})
            except Exception as exc:
                try:
                    server_wire.send({"error": str(exc)})
                except Exception:
                    pass
            finally:
                remote.close()
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.workers.append(thread)
        return Wire(local)

    def join(self):
        for worker in self.workers:
            worker.join(timeout=4)
            if worker.is_alive():
                raise AssertionError("Transfer worker hung")


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.local = Store(self.root / "linux")
        self.peer = InMemoryPeer(self.root / "windows", self.root / "inbox")
        self.sync = Synchronizer(self.peer, self.local.root, self.root / "baseline.json")

    def tearDown(self):
        self.peer.join()
        self.temp.cleanup()

    def write(self, side, name, value):
        root = self.local.root if side == "linux" else self.peer.server.shared.root
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)

    def test_bidirectional_large_and_empty_transfers_then_edits(self):
        content = b"block\0" * 100000  # spans multiple chunks and fragmented frames
        self.write("linux", "folder/linux.bin", content)
        self.write("windows", "windows.txt", b"from Windows")
        self.write("windows", "empty", b"")
        self.sync.run()
        self.assertEqual(self.local.manifest(), self.peer.server.shared.manifest())
        self.assertEqual((self.peer.server.shared.root / "folder/linux.bin").read_bytes(), content)
        self.write("windows", "windows.txt", b"new Windows edit")
        self.sync.run()
        self.assertEqual((self.local.root / "windows.txt").read_bytes(), b"new Windows edit")

    def test_concurrent_changes_converge_without_losing_either(self):
        self.write("linux", "document.txt", b"base")
        self.sync.run()
        self.write("linux", "document.txt", b"Linux edit")
        self.write("windows", "document.txt", b"Windows edit")
        self.sync.run()
        self.assertEqual(self.local.manifest(), self.peer.server.shared.manifest())
        self.assertEqual((self.local.root / "document.txt").read_bytes(), b"Linux edit")
        conflicts = list(self.local.root.glob("document.conflict-windows-*.txt"))
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].read_bytes(), b"Windows edit")
        self.sync.run()
        self.assertEqual(len(list(self.local.root.glob("*.txt"))), 2)

    def test_delete_propagates_to_trash_and_offline_edit_wins_over_delete(self):
        self.write("linux", "document", b"base")
        self.sync.run()
        (self.local.root / "document").unlink()
        self.sync.run()
        self.assertFalse((self.peer.server.shared.root / "document").exists())
        self.assertEqual(next((self.peer.server.shared.root / ".lanbridge-trash").rglob("document")).read_bytes(), b"base")
        self.write("linux", "document", b"new base")
        self.sync.run()
        (self.local.root / "document").unlink()
        self.write("windows", "document", b"edited while Linux deleted")
        self.sync.run()
        self.assertEqual((self.local.root / "document").read_bytes(), b"edited while Linux deleted")

    def test_inbox_transfer_cannot_read_shared_arbitrary_path(self):
        self.write("linux", "send.txt", b"explicit send")
        push(self.peer, "inbox", self.local.root / "send.txt", "send.txt")
        self.assertEqual((self.peer.server.inbox.root / "send.txt").read_bytes(), b"explicit send")
        with self.assertRaises(ProtocolError):
            pull(self.peer, self.local, "../outside")

    def test_first_sync_conflicting_files_keep_both(self):
        self.write("linux", "note", b"one")
        self.write("windows", "note", b"two")
        self.sync.run()
        self.assertEqual(sorted(p.read_bytes() for p in self.local.root.iterdir() if p.is_file()), [b"one", b"two"])
        self.assertEqual(self.local.manifest(), self.peer.server.shared.manifest())
