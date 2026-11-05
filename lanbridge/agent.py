"""Linux connection supervisor, independent heartbeat and transfer workers."""
from __future__ import annotations
import logging
import socket
from pathlib import Path
import subprocess
import threading
import time
from contextlib import suppress
from . import __version__
from .clipboard import Clip, ClipboardLink
from .config import atomic_json, state_dir, load
from .files import Store, push, pull
from .offers import Offers
from .sync import Synchronizer
from .wire import Client
from .workspaces import Viewers, hypr_json

log = logging.getLogger(__name__)


class Agent:
    def __init__(self, config_path, config, clipboard_adapter):
        self.config_path, self.config = config_path, config
        self.state = state_dir()
        self.client = Client(config)
        self.clipboard = ClipboardLink(clipboard_adapter)
        self.viewers = Viewers(config_path, config)
        self.offers = Offers(self.state)
        self.inbox = Store(Path(config["inbox"]))
        self.sync = Synchronizer(self.client, Path(config["shared"]), self.state / "sync-baseline.json")
        self.stopped = threading.Event()
        self.connected = threading.Event()
        self.transfer_error = None
        self.audio = None
        self.audio_stop = threading.Event()
        self.audio_wire = None
        self.audio_player = None
        self.audio_retry = 0
        self.clipboard_error = None
        self.connection_lost_at = None
        self.reconnect_grace = 30
        self.desktop_error = None

    def status(self, connected, **extra):
        atomic_json(self.state / "status.json", {"running": not self.stopped.is_set(),
                    "connected": connected, "updated": time.time(), "version": __version__,
                    "transfer_error": self.transfer_error, "clipboard_error": self.clipboard_error,
                    "desktop_error": self.desktop_error, "viewers": self.viewers.snapshot(), **extra})

    def run(self):
        threading.Thread(target=self.transfers, daemon=True).start()
        try:
            while not self.stopped.is_set():
                try:
                    settings = load(self.config_path)
                    for setting in ("clipboard", "sync", "audio"):
                        self.config[setting] = settings[setting]
                    if not self.connected.is_set():
                        hello, _ = self.client.call("hello")
                        self.client.session = hello["session"]
                        self.clipboard.seen = None
                        atomic_json(self.state / "session.json", {"session": self.client.session})
                        self.connected.set()
                    caps, _ = self.client.call("heartbeat")
                    self.connection_lost_at = None
                    self.exchange_clipboard(caps)
                    self.update_desktop(caps)
                    self.status(True, interactive=caps.get("interactive", False),
                                displays=caps["displays"], blocked_workspaces=self.viewers.blocked)
                    self.stopped.wait(0.7)
                except Exception as exc:
                    log.warning("Connection unavailable: %s", type(exc).__name__)
                    self.connected.clear()
                    expired = self.expire_disconnected_views()
                    self.stop_audio()
                    self.status(False, recovering=not expired,
                                message="Waiting for the approved Windows companion on TCP 4242")
                    self.stopped.wait(3)
        finally:
            self.connected.clear()
            self.viewers.stop()
            self.stop_audio()
            try:
                if self.client.session:
                    self.client.call("disconnect")
            except Exception:
                pass
            (self.state / "session.json").unlink(missing_ok=True)
            self.status(False)

    def expire_disconnected_views(self, now=None):
        now = time.monotonic() if now is None else now
        if self.connection_lost_at is None:
            self.connection_lost_at = now
        if now - self.connection_lost_at < self.reconnect_grace:
            return False
        self.viewers.stop()
        (self.state / "session.json").unlink(missing_ok=True)
        return True

    def update_desktop(self, caps):
        self.desktop_error = None
        try:
            self.viewers.reconcile(caps["displays"])
            self.update_audio(caps)
        except Exception as exc:
            self.desktop_error = type(exc).__name__
            log.warning("Desktop integration will retry: %s", self.desktop_error)

    def exchange_clipboard(self, caps):
        if not self.config.get("clipboard", True) or not caps.get("clipboard"):
            self.clipboard_error = None
            return
        try:
            clip = self.clipboard.changed()
            if clip:
                self.client.call("clipboard_set", clip=clip.message())
            reply, _ = self.client.call("clipboard_get", known=self.clipboard.seen)
            if reply.get("clip"):
                self.clipboard.apply(Clip.parse(reply["clip"]))
            self.clipboard_error = None
        except Exception as exc:
            # A temporarily locked native clipboard must not close both displays
            # or lose the pending local copy. Retry it on the next pass.
            self.clipboard.seen = None
            self.clipboard_error = type(exc).__name__
            log.warning("Clipboard will retry: %s", type(exc).__name__)

    def transfers(self):
        last_sync = 0
        while not self.stopped.wait(1):
            if not self.connected.is_set():
                continue
            try:
                for item in self.offers.list():
                    self.offers.get(item["id"])
                    push(self.client, "inbox", Path(item["path"]), item["name"])
                    self.offers.done(item["id"])
                reply, _ = self.client.call("offers")
                for item in reply["offers"]:
                    pull(self.client, self.inbox, item["name"], offer=item["id"], source=item["sha256"])
                    self.client.call("offer_done", offer=item["id"])
                if self.config.get("sync", True) and time.monotonic() - last_sync > 10:
                    self.sync.run()
                    last_sync = time.monotonic()
                self.transfer_error = None
            except Exception as exc:
                self.transfer_error = type(exc).__name__
                log.warning("Transfer/sync will retry: %s", type(exc).__name__)
                self.stopped.wait(5)

    def update_audio(self, caps):
        active = hypr_json("activewindow").get("class", "").startswith("local.lanbridge.screen")
        wanted = active and self.config.get("audio", False) and caps.get("audio", False)
        if not wanted:
            self.stop_audio()
        elif (self.audio is None or not self.audio.is_alive()) and time.monotonic() >= self.audio_retry:
            self.audio_stop = threading.Event()
            self.audio = threading.Thread(target=self.play_audio, args=(self.audio_stop,), daemon=True)
            self.audio.start()

    def play_audio(self, stop):
        wire, player = None, None
        try:
            wire = self.client.connect("audio")
            self.audio_wire = wire
            if stop.is_set():
                return
            meta, _ = wire.recv()
            if meta.get("format") != "s16le" or meta.get("rate") != 48000 or meta.get("channels") != 2:
                return
            player = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "-f", "s16le",
                                       "-ar", "48000", "-ch_layout", "stereo", "-i", "pipe:0"], stdin=subprocess.PIPE, bufsize=0)
            self.audio_player = player
            while not stop.is_set() and not self.stopped.is_set():
                if not wire.readable(0.2):
                    continue
                message, block = wire.recv()
                if message.get("kind") != "audio" or len(block) > 38400:
                    break
                player.stdin.write(block)
        except Exception:
            if not stop.is_set():
                log.warning("Audio stream unavailable")
                self.audio_retry = time.monotonic() + 10
        finally:
            if wire:
                wire.stream.close()
            if player:
                with suppress(OSError):
                    player.stdin.close()
                player.terminate()
                try:
                    player.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    player.kill()
                    player.wait()
            self.audio_wire = None
            self.audio_player = None

    def stop_audio(self):
        self.audio_stop.set()
        player = self.audio_player
        if player:
            with suppress(OSError):
                player.terminate()
        if self.audio:
            self.audio.join(timeout=1)
            if not self.audio.is_alive():
                self.audio = None
