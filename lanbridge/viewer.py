"""A native tiled GTK4 view; one frame buffer and bounded input queue."""
from __future__ import annotations
from pathlib import Path
import queue
import threading
import time
import logging
from .config import read_json, state_dir
from .input import normalized_point
from .wire import Client
from .display import DisplayStream, CoalescedCall

log = logging.getLogger(__name__)


def run(config_path, config, monitor):
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk, Gio, GLib

    class Viewer(Gtk.Application):
        def __init__(self):
            super().__init__(application_id=f"local.lanbridge.screen{monitor}", flags=Gio.ApplicationFlags.NON_UNIQUE)
            self.closed = threading.Event()
            self.events = queue.Queue(maxsize=256)
            self.lock = threading.Lock()
            self.latest = None
            self.point = None
            self.width, self.height = 1920, 1080
            self.wire = None
            self.interactive = False
            self.focused = False
            self.pressed_button = None
            self.reset_stream = threading.Event()
            self.message = "Connecting to Windows…"
            self.has_frame = False
            self.last_decode_warning = 0
            self.decode_error = False

        def do_activate(self):
            self.window = Gtk.ApplicationWindow(application=self, title=f"Windows display {monitor} · Lan Bridge")
            self.window.set_default_size(1100, 700)
            self.window.set_decorated(False)
            self.picture = Gtk.Picture.new()
            self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            self.picture.set_can_shrink(True)
            self.picture.set_hexpand(True)
            self.picture.set_vexpand(True)
            self.picture.set_focusable(True)
            overlay = Gtk.Overlay(child=self.picture)
            self.label = Gtk.Label(label="Connecting to Windows…")
            self.label.set_halign(Gtk.Align.CENTER)
            self.label.set_valign(Gtk.Align.CENTER)
            overlay.add_overlay(self.label)
            # This small native control also provides a remote Windows key without
            # capturing Super+1..7, which remain local workspace shortcuts.
            start = Gtk.Button(label="Windows Start")
            start.set_halign(Gtk.Align.END)
            start.set_valign(Gtk.Align.START)
            start.set_opacity(0.65)
            start.connect("clicked", lambda *_: (self.enqueue({"kind": "key", "code": 125, "down": True}), self.enqueue({"kind": "key", "code": 125, "down": False})))
            overlay.add_overlay(start)
            self.window.set_child(overlay)
            motion = Gtk.EventControllerMotion.new()
            motion.connect("motion", self.motion)
            self.picture.add_controller(motion)
            click = Gtk.GestureClick.new()
            click.set_button(0)
            click.connect("pressed", self.click, True)
            click.connect("released", self.click, False)
            self.picture.add_controller(click)
            keys = Gtk.EventControllerKey.new()
            keys.connect("key-pressed", self.key, True)
            keys.connect("key-released", self.key, False)
            self.window.add_controller(keys)
            scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES)
            scroll.connect("scroll", lambda _c, dx, dy: self.enqueue({"kind": "scroll", "dx": dx, "dy": dy}))
            self.picture.add_controller(scroll)
            self.window.connect("notify::is-active", self.focus)
            self.window.connect("close-request", self.close_requested)
            self.window.present()
            self.picture.grab_focus()
            self.redraw = CoalescedCall(GLib.idle_add, self.render)
            threading.Thread(target=self.network, daemon=True).start()

        def motion(self, _controller, x, y):
            point = normalized_point(x, y, self.picture.get_width(), self.picture.get_height(), self.width, self.height)
            if point and self.interactive and self.window.is_active():
                with self.lock:
                    self.point = {"kind": "move", "u": point[0], "v": point[1]}
            return point

        def click(self, gesture, _count, x, y, down):
            inside = self.motion(None, x, y)
            if down:
                button = gesture.get_current_button()
                if inside is None or button not in (1, 2, 3):
                    return
                self.pressed_button = button
            else:
                button = self.pressed_button
                self.pressed_button = None
                if button is None:
                    return
            self.picture.grab_focus()
            # Flush the matching position before the click, preserving ordering.
            with self.lock:
                point, self.point = self.point, None
            if point:
                self.enqueue(point)
            self.enqueue({"kind": "button", "button": button, "down": down})

        def key(self, _controller, keyval, keycode, state, down):
            code = keycode - 8  # Wayland XKB hardware codes -> Linux evdev codes
            if code in (125, 126) or state & Gdk.ModifierType.SUPER_MASK:
                return False
            return self.enqueue({"kind": "key", "code": code, "down": down})

        def enqueue(self, event):
            if not self.interactive:
                return False
            try:
                self.events.put_nowait(event)
                return True
            except queue.Full:
                # Reconnect releases remote keys without removing the window.
                self.reset_stream.set()
                return False

        def focus(self, *_):
            self.focused = self.window.is_active()
            if not self.focused:
                with self.lock:
                    self.point = None
                while True:
                    try:
                        self.events.get_nowait()
                    except queue.Empty:
                        break
                self.enqueue({"kind": "release"})
            if hasattr(self, "redraw"):
                self.redraw.request()

        def controls(self):
            if self.reset_stream.is_set():
                self.reset_stream.clear()
                raise ConnectionResetError("Input queue recovery")
            events = []
            for _ in range(32):
                try:
                    events.append(self.events.get_nowait())
                except queue.Empty:
                    break
            with self.lock:
                point, self.point = self.point, None
            return self.focused, events, point

        def stream_state(self, state, metadata):
            if state == "input_status":
                with self.lock:
                    self.message = "" if metadata.get("available") else "Windows is blocking remote input · Check elevated or secure windows"
                self.redraw.request()
                return
            self.interactive = state == "connected" and metadata.get("interactive", False)
            if state != "connected":
                with self.lock:
                    self.point = None
                while True:
                    try:
                        self.events.get_nowait()
                    except queue.Empty:
                        break
            with self.lock:
                message = (("" if self.interactive else "View only · Windows input guard needs installation") if state == "connected"
                           else "Video stalled · Recovering…" if state == "stalled" else "Reconnecting to Windows…")
                changed = self.message != message
                self.message = message
            if changed:
                self.redraw.request()

        def frame(self, message, data):
            with self.lock:
                self.latest = (message, data)
            if self.focused:
                self.redraw.request()

        def network(self):
            try:
                client = Client(config)
                def connect():
                    runtime = read_json(state_dir() / "session.json", {})
                    client.session = runtime.get("session")
                    return client.connect("display", monitor=monitor, connect_timeout=3, timeout=3)
                DisplayStream(connect, self.controls, self.frame, self.stream_state, self.closed).run()
            except Exception as exc:
                log.error("Viewer startup failed: %s", type(exc).__name__)
                self.stream_state("reconnecting", {})

        def render(self):
            if self.closed.is_set():
                self.quit()
                return False
            with self.lock:
                frame = self.latest if self.focused else None
                if frame:
                    self.latest = None
            if frame:
                message, data = frame
                try:
                    texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
                    self.picture.set_paintable(texture)
                    self.width, self.height = message["width"], message["height"]
                    self.has_frame = True
                    self.decode_error = False
                except GLib.Error as exc:
                    self.decode_error = True
                    if time.monotonic() - self.last_decode_warning > 5:
                        log.warning("Video frame decode failed: %s", type(exc).__name__)
                        self.last_decode_warning = time.monotonic()
            with self.lock:
                message = self.message
            if not message and self.decode_error:
                message = "Video decoder is retrying…"
            self.label.set_visible(bool(message) or not self.has_frame)
            self.label.set_label(message or "Waiting for Windows video…")
            return False

        def close_requested(self, *_):
            self.closed.set()
            self.quit()
            return False

    Viewer().run([])
