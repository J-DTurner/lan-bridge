"""A native tiled GTK4 view; one frame buffer and bounded input queue."""
from __future__ import annotations
from pathlib import Path
import queue
import threading
import time
from .config import read_json, state_dir
from .input import normalized_point
from .wire import Client


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
            threading.Thread(target=self.network, daemon=True).start()
            GLib.timeout_add(33, self.render)

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
                # Disconnect forces the server to release every pressed key.
                self.closed.set()
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

        def writer(self):
            previous, last = None, 0
            try:
                while not self.closed.wait(0.008):
                    active = self.focused
                    if active != previous or time.monotonic() - last > 1:
                        self.wire.send({"kind": "activity", "active": active})
                        previous, last = active, time.monotonic()
                    while True:
                        try:
                            event = self.events.get_nowait()
                        except queue.Empty:
                            break
                        if active or event["kind"] == "release":
                            self.wire.send(event)
                    with self.lock:
                        point, self.point = self.point, None
                    if active and point:
                        self.wire.send(point)
            except Exception:
                self.closed.set()

        def network(self):
            try:
                runtime = read_json(state_dir() / "session.json", {})
                client = Client(config)
                client.session = runtime.get("session")
                self.wire = client.connect("display", monitor=monitor)
                metadata, _ = self.wire.recv()
                if "error" in metadata:
                    raise ValueError(metadata["error"])
                self.interactive = metadata.get("interactive", False)
                threading.Thread(target=self.writer, daemon=True).start()
                while not self.closed.is_set():
                    message, data = self.wire.recv()
                    if message.get("kind") == "frame":
                        if not (1 <= message["width"] <= 8192 and 1 <= message["height"] <= 8192):
                            raise ValueError("Invalid frame dimensions")
                        with self.lock:
                            self.latest = (message, data)
            except Exception:
                pass
            finally:
                self.closed.set()
                if self.wire:
                    self.wire.stream.close()
                GLib.idle_add(self.quit)

        def render(self):
            if self.closed.is_set():
                self.quit()
                return False
            with self.lock:
                frame, self.latest = self.latest, None
            if frame:
                message, data = frame
                try:
                    texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
                    self.picture.set_paintable(texture)
                    self.width, self.height = message["width"], message["height"]
                    self.label.set_visible(not self.interactive)
                    self.label.set_label("View only · Windows input guard needs installation")
                except GLib.Error:
                    self.closed.set()
            return True

        def close_requested(self, *_):
            self.closed.set()
            if self.wire:
                self.wire.stream.close()
            self.quit()
            return False

    Viewer().run([])
