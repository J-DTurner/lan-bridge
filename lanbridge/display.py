"""Display I/O with one TLS owner and recovery independent of window lifetime."""
from __future__ import annotations
import logging
import time
import threading
from .wire import ProtocolError

log = logging.getLogger(__name__)


class CoalescedCall:
    """Schedule at most one pending GUI callback, even during a frame burst."""
    def __init__(self, schedule, callback):
        self.schedule, self.callback = schedule, callback
        self.lock = threading.Lock()
        self.pending = False

    def request(self):
        with self.lock:
            if self.pending:
                return
            self.pending = True
        self.schedule(self.dispatch)

    def dispatch(self):
        with self.lock:
            self.pending = False
        self.callback()
        return False  # remove the GLib idle source; no permanent render timer


class StreamStalled(TimeoutError):
    reason = "FRAME_STALLED"


def error_code(exc):
    # Log categories only: never include frames, clipboard, keys or peer identity.
    reason = getattr(exc, "reason", None)
    return f"{type(exc).__name__}:{reason}" if isinstance(reason, str) else type(exc).__name__


def rejected(message):
    exc = ProtocolError("Display request rejected")
    exc.reason = {"Display already has a viewer": "DISPLAY_BUSY",
                  "No active approved sharing session": "SESSION_EXPIRED",
                  "Incompatible protocol": "PROTOCOL_VERSION"}.get(message, "DISPLAY_REJECTED")
    return exc


class DisplayStream:
    def __init__(self, connect, controls, on_frame, on_state, stopped, *, clock=time.monotonic):
        self.connect, self.controls = connect, controls
        self.on_frame, self.on_state = on_frame, on_state
        self.stopped, self.clock = stopped, clock

    def run(self):
        backoff = 0.5
        while not self.stopped.is_set():
            wire = None
            try:
                self.on_state("connecting", {})
                wire = self.connect()
                metadata, extra = wire.recv(timeout=3)
                if "error" in metadata:
                    raise rejected(metadata["error"])
                if extra or "display" not in metadata:
                    raise ProtocolError("Display was not accepted")
                self.on_state("connected", metadata)
                previous, last_activity = None, 0
                last_received = last_frame = self.clock()
                stalled = False
                while not self.stopped.is_set():
                    active, events, point = self.controls()
                    now = self.clock()
                    if active != previous:
                        last_frame = now
                        if stalled:
                            stalled = False
                            self.on_state("connected", metadata)
                    if active != previous or now - last_activity >= 1:
                        wire.send({"kind": "activity", "active": active})
                        previous, last_activity = active, now
                    if active and now - last_frame >= 6:
                        raise StreamStalled("No video frames received")
                    if active and now - last_frame >= 3 and not stalled:
                        stalled = True
                        self.on_state("stalled", {})
                        # Both messages are supported by the original companion.
                        wire.send({"kind": "release"})
                        wire.send({"kind": "activity", "active": True})
                    if now - last_received >= 10:
                        raise TimeoutError("Display transport stopped responding")
                    if stalled:
                        events, point = [], None
                    for event in events:
                        if active or event.get("kind") == "release":
                            wire.send(event)
                    if active and point:
                        wire.send(point)
                    if not wire.readable(0.016 if active else 0.25):
                        continue
                    message, data = wire.recv(timeout=3)
                    last_received = self.clock()
                    if "error" in message:
                        raise rejected(message["error"])
                    if message.get("kind") == "frame":
                        if (type(message.get("width")) is not int or type(message.get("height")) is not int or
                            not 1 <= message["width"] <= 8192 or not 1 <= message["height"] <= 8192 or not data):
                            raise ProtocolError("Invalid frame dimensions")
                        self.on_frame(message, data)
                        last_frame = last_received
                        if stalled:
                            stalled = False
                            self.on_state("connected", metadata)
                        backoff = 0.5
                    elif message.get("kind") == "input_status":
                        self.on_state("input_status", message)
                    elif message.get("kind") != "idle":
                        raise ProtocolError("Unknown display message")
                    else:
                        backoff = 0.5
            except Exception as exc:
                if not self.stopped.is_set():
                    code = error_code(exc)
                    log.warning("Display stream reconnecting: %s", code)
                    self.on_state("reconnecting", {"error": code})
            finally:
                if wire:
                    wire.stream.close()  # only this thread ever operates the TLS socket
            if not self.stopped.is_set():
                self.stopped.wait(backoff)
                backoff = min(5, backoff * 2)


def serve_display(wire, capture, inputs, check_session, stopped, fps, *, clock=time.monotonic):
    """One worker captures, receives control and sends frames on this connection."""
    active, next_frame = False, 0
    input_blocked, retry_input = False, 0
    interval = 1 / max(1, min(30, fps))

    def input_status(available):
        wire.send({"kind": "input_status", "available": available})

    while not stopped.is_set():
        check_session()
        now = clock()
        if now >= next_frame:
            if active:
                data, width, height = capture.frame()
                wire.send({"kind": "frame", "width": width, "height": height}, data)
            else:
                wire.send({"kind": "idle"})
            next_frame = now + (interval if active else 0.5)
        if not wire.readable(min(0.05, max(0, next_frame - clock()))):
            continue
        event, extra = wire.recv()
        check_session()
        if extra:
            raise ProtocolError("Unexpected input payload")
        kind = event.get("kind")
        if kind == "activity":
            active = event.get("active") is True
            next_frame = 0
            if hasattr(capture, "set_active"):
                try:
                    capture.set_active(active)
                except OSError as exc:
                    log.warning("Display sleep inhibition unavailable: %s", error_code(exc))
        if inputs and (not active or clock() >= retry_input):
            try:
                if not active or kind == "release" or input_blocked:
                    inputs.release()
                if active and kind not in ("activity", "release"):
                    inputs.handle(event)
                if input_blocked:
                    input_status(True)
                input_blocked = False
            except OSError as exc:
                # UIPI/protected windows can reject SendInput. Keep video alive;
                # do not turn an input permission failure into a closed workspace.
                if not input_blocked:
                    log.warning("Remote input temporarily blocked: %s", error_code(exc))
                    input_status(False)
                input_blocked = True
                retry_input = clock() + 1
