"""Windows companion TLS listener and finite, authenticated feature handlers."""
from __future__ import annotations
import importlib.util
import ipaddress
import logging
from pathlib import Path
import secrets
import socket
import threading
import time
from . import PROTOCOL, __version__
from .clipboard import Clip, ClipboardLink
from .config import state_dir, atomic_json, read_json, load
from .files import Store, confined, digest, send_file
from .offers import Offers
from .wire import Wire, ProtocolError, server_context, verify_peer

log = logging.getLogger(__name__)


class Sessions:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.token = None
        self.deadline = 0

    def open(self):
        with self.lock:
            self.token = secrets.token_hex(32)
            self.deadline = self.clock() + 20
            return self.token

    def check(self, token, renew=False):
        with self.lock:
            if not isinstance(token, str) or self.token is None or not secrets.compare_digest(token, self.token) or self.clock() > self.deadline:
                raise ProtocolError("No active approved sharing session")
            if renew:
                self.deadline = self.clock() + 20

    def close(self):
        with self.lock:
            self.token = None
            self.deadline = 0

    def connected(self):
        with self.lock:
            return self.token is not None and self.clock() <= self.deadline


class Server:
    def __init__(self, config, clipboard_adapter, screen_backend):
        self.config = config
        self.state = state_dir()
        self.shared, self.inbox = Store(Path(config["shared"])), Store(Path(config["inbox"]))
        self.clipboard = ClipboardLink(clipboard_adapter)
        self.clip_lock = threading.RLock()
        self.latest_clip = None
        self.offers = Offers(self.state)
        self.screens = screen_backend
        self.sessions = Sessions()
        self.stopped = threading.Event()
        self.slots = threading.BoundedSemaphore(12)
        self.screen_lock = threading.Lock()
        self.active_displays = set()
        self.file_lock = threading.RLock()
        self.workers = []
        self.context = server_context(config["identity"], config["peer_certificate"])

    def input_guard(self):
        from .engine import guard_verified
        return guard_verified(self.config)

    def capabilities(self):
        return {"clipboard": self.config.get("clipboard", True), "files": True,
                "sync": self.config.get("sync", True), "displays": self.screens.monitors(),
                "interactive": self.input_guard(), "audio": self.config.get("audio", False) and importlib.util.find_spec("soundcard") is not None}

    def serve(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.config.get("listen", "0.0.0.0"), self.config["port"]))
        listener.listen(12)
        listener.settimeout(1)
        atomic_json(self.state / "status.json", {"running": True, "connected": False, "version": __version__})
        try:
            while not self.stopped.is_set():
                atomic_json(self.state / "status.json", {"running": True, "connected": self.sessions.connected(),
                            "updated": time.time(), "version": __version__})
                if (self.state / "stop.request").exists():
                    (self.state / "stop.request").unlink(missing_ok=True)
                    self.stopped.set()
                    break
                try:
                    raw, address = listener.accept()
                except socket.timeout:
                    continue
                # Installer also creates a Private/LocalSubnet firewall rule.
                # Require the explicitly configured peer address on this listener.
                if address[0] != self.config["host"] or not self.slots.acquire(blocking=False):
                    raw.close()
                    continue
                worker = threading.Thread(target=self.handle, args=(raw,), daemon=True)
                self.workers = [w for w in self.workers if w.is_alive()]
                self.workers.append(worker)
                worker.start()
        finally:
            listener.close()
            self.sessions.close()
            deadline = time.monotonic() + 2
            for worker in self.workers:
                worker.join(timeout=max(0, deadline - time.monotonic()))
            atomic_json(self.state / "status.json", {"running": False, "connected": False})

    def handle(self, raw):
        wire = None
        try:
            raw.settimeout(10)
            sock = self.context.wrap_socket(raw, server_side=True)
            verify_peer(sock, self.config["peer_fingerprint"])
            wire = Wire(sock)
            request, payload = wire.recv()
            if request.get("protocol") != PROTOCOL or payload:
                raise ProtocolError("Incompatible protocol")
            op = request.get("op")
            if op == "hello":
                token = self.sessions.open()
                wire.send({"session": token, "protocol": PROTOCOL, "version": __version__, **self.capabilities()})
                return
            self.sessions.check(request.get("session"), renew=op == "heartbeat")
            wire.authorize = lambda: self.sessions.check(request.get("session"))
            settings = load(Path(self.config["config_path"])) if self.config.get("config_path") else self.config
            for setting in ("clipboard", "sync", "audio"):
                self.config[setting] = settings.get(setting, self.config.get(setting))
            if op == "heartbeat":
                atomic_json(self.state / "status.json", {"running": True, "connected": True, "updated": time.time(), "version": __version__})
                wire.send({"ok": True, **self.capabilities()})
            elif op == "disconnect":
                wire.send({"ok": True})
                self.sessions.close()
            elif op.startswith("clipboard_"):
                self.handle_clipboard(wire, request)
            elif op == "manifest":
                if not self.config.get("sync", True):
                    raise ProtocolError("Folder sync is disabled")
                with self.file_lock:
                    wire.send({"files": self.shared.manifest()})
            elif op == "delete":
                if not self.config.get("sync", True):
                    raise ProtocolError("Folder sync is disabled")
                with self.file_lock:
                    self.shared.delete(request["name"], request["expected"])
                wire.send({"ok": True})
            elif op in ("put", "get"):
                with self.file_lock:
                    self.handle_file(wire, request)
            elif op == "offers":
                wire.send({"offers": [{k: v for k, v in o.items() if k != "path"} for o in self.offers.list()]})
            elif op == "offer_done":
                self.offers.done(request["offer"])
                wire.send({"ok": True})
            elif op == "display":
                self.handle_display(wire, request)
            elif op == "audio":
                self.handle_audio(wire, request)
            else:
                raise ProtocolError("Unknown operation")
        except (EOFError, ConnectionError, TimeoutError):
            pass
        except Exception as exc:
            # Never log payloads, clipboard text, keys, filenames or tokens.
            log.warning("Peer operation failed: %s", type(exc).__name__)
            if wire:
                try:
                    wire.send({"error": str(exc) if isinstance(exc, ProtocolError) else "Native operation failed; inspect local diagnostics"})
                except (OSError, ProtocolError):
                    pass
        finally:
            if wire:
                wire.stream.close()
            raw.close()
            self.slots.release()

    def handle_clipboard(self, wire, request):
        if not self.config.get("clipboard", True):
            raise ProtocolError("Clipboard sharing is disabled")
        with self.clip_lock:
            if request["op"] == "clipboard_set":
                clip = Clip.parse(request["clip"])
                self.clipboard.apply(clip)
                self.latest_clip = clip
                wire.send({"ok": True})
            elif request["op"] == "clipboard_get":
                changed = self.clipboard.changed()
                if changed:
                    self.latest_clip = changed
                clip = self.latest_clip
                wire.send({"clip": clip.message() if clip and clip.key != request.get("known") else None})
            else:
                raise ProtocolError("Unknown clipboard operation")

    def handle_file(self, wire, request):
        scope = request.get("scope")
        if scope == "shared" and self.config.get("sync", True):
            store = self.shared
        elif scope == "inbox" and request["op"] == "put":
            store = self.inbox
        elif scope == "offer" and request["op"] == "get":
            offer = self.offers.get(request["offer"])
            path = Path(offer["path"])
            wire.send({k: offer[k] for k in ("name", "size", "sha256")})
            send_file(wire, path)
            return
        else:
            raise ProtocolError("Invalid file scope")
        if request["op"] == "put":
            store.receive(wire, request, inbox=scope == "inbox")
        else:
            path = confined(store.root, request["name"])
            checksum = digest(path)
            if checksum is None:
                raise ProtocolError("File is no longer available")
            wire.send({"name": request["name"], "size": path.stat().st_size, "sha256": checksum})
            send_file(wire, path)

    def handle_display(self, wire, request):
        monitor_id = request.get("monitor")
        if type(monitor_id) is not int:
            raise ProtocolError("Invalid display ID")
        with self.screen_lock:
            if monitor_id in self.active_displays:
                raise ProtocolError("Display already has a viewer")
            self.active_displays.add(monitor_id)
        capture, inputs = None, None
        closed = threading.Event()
        activity = {"active": False}
        try:
            capture = self.screens.Capture(monitor_id, self.config.get("max_width", 1920))
            interactive = self.input_guard()
            inputs = self.screens.Input(capture.monitor, capture.virtual) if interactive else None
            wire.send({"display": monitor_id, "interactive": interactive, **capture.monitor})

            def receive():
                try:
                    while not closed.is_set():
                        event, extra = wire.recv()
                        if closed.is_set():
                            break
                        self.sessions.check(request["session"])
                        if extra:
                            raise ProtocolError("Unexpected input payload")
                        if event.get("kind") == "activity":
                            activity["active"] = event.get("active") is True
                            if not activity["active"] and inputs:
                                inputs.release()
                        elif inputs and activity["active"]:
                            inputs.handle(event)
                except Exception:
                    closed.set()

            thread = threading.Thread(target=receive, daemon=True)
            thread.start()
            interval = 1 / max(1, min(30, self.config.get("fps", 15)))
            while not closed.is_set() and not self.stopped.is_set():
                self.sessions.check(request["session"])
                start = time.monotonic()
                if activity["active"]:
                    frame, width, height = capture.frame()
                    wire.send({"kind": "frame", "width": width, "height": height}, frame)
                else:
                    wire.send({"kind": "idle"})
                closed.wait(max(0.001, (interval if activity["active"] else 0.5) - (time.monotonic() - start)))
        finally:
            closed.set()
            try:
                wire.stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            if "thread" in locals():
                thread.join(timeout=1)
            if inputs:
                inputs.release()
            if capture:
                capture.close()
            with self.screen_lock:
                self.active_displays.discard(monitor_id)

    def handle_audio(self, wire, request):
        if not self.config.get("audio", False):
            raise ProtocolError("Audio sharing is disabled")
        import soundcard as sc
        import numpy as np
        speaker = sc.default_speaker()
        mic = sc.get_microphone(id=speaker.id, include_loopback=True)
        wire.send({"format": "s16le", "rate": 48000, "channels": 2})
        with mic.recorder(samplerate=48000, channels=2) as recorder:
            while not self.stopped.is_set():
                self.sessions.check(request["session"])
                data = recorder.record(numframes=960)
                pcm = (np.clip(data, -1, 1) * 32767).astype("<i2").tobytes()
                wire.send({"kind": "audio"}, pcm)
