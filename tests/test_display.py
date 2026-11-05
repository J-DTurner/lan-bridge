from collections import deque
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from lanbridge.display import DisplayStream, serve_display
from lanbridge.agent import Agent
from lanbridge.server import Server
from lanbridge.platform.windows_screen import Capture


class Stop:
    def __init__(self): self.stopped = False
    def is_set(self): return self.stopped
    def set(self): self.stopped = True
    def wait(self, timeout): return self.stopped


class FakeWire:
    def __init__(self, packets, stop=None):
        self.packets = deque(packets)
        self.sent, self.owners = [], set()
        self.closed = False
        self.stream = SimpleNamespace(close=self.close, shutdown=lambda *_: None)
        self.stop = stop

    def touch(self): self.owners.add(threading.get_ident())
    def close(self): self.touch(); self.closed = True
    def send(self, message, payload=b""): self.touch(); self.sent.append((message, payload))
    def recv(self, *, timeout=None):
        self.touch()
        item = self.packets.popleft()
        if isinstance(item, Exception): raise item
        return item
    def readable(self, timeout):
        self.touch()
        if not self.packets:
            if self.stop: self.stop.set()
            return False
        return True


META = ({"display": 1, "interactive": True}, b"")
FRAME = ({"kind": "frame", "width": 32, "height": 24}, b"synthetic frame data")


class DisplayRecoveryTests(unittest.TestCase):
    def test_stream_failure_reconnects_without_stopping_window(self):
        stop, states, frames = Stop(), [], []
        first = FakeWire([META, FRAME, EOFError()])
        second = FakeWire([META, FRAME])
        connections = deque([first, second])
        def frame(message, data):
            frames.append(data)
            if len(frames) == 2: stop.set()
        stream = DisplayStream(lambda: connections.popleft(), lambda: (True, [], None),
                               frame, lambda state, _: states.append(state), stop)
        with self.assertLogs("lanbridge.display", level="WARNING"):
            stream.run()
        self.assertEqual(frames, [FRAME[1], FRAME[1]])
        self.assertIn("reconnecting", states)
        self.assertTrue(first.closed and second.closed)
        self.assertEqual(first.owners | second.owners, {threading.get_ident()})

    def test_busy_display_is_retried_and_inputs_share_one_tls_owner(self):
        stop, states = Stop(), []
        rejected = FakeWire([({"error": "Display already has a viewer"}, b"")])
        healthy = FakeWire([META, FRAME])
        connections = deque([rejected, healthy])
        event = {"kind": "key", "code": 30, "down": True}
        stream = DisplayStream(lambda: connections.popleft(), lambda: (True, [event], None),
                               lambda *_: stop.set(), lambda state, _: states.append(state), stop)
        with self.assertLogs("lanbridge.display", level="WARNING") as logs:
            stream.run()
        self.assertIn("DISPLAY_BUSY", " ".join(logs.output))
        self.assertTrue(any(m == event for m, _ in healthy.sent))
        self.assertEqual(healthy.owners, {threading.get_ident()})

    def test_invalid_frame_does_not_terminate_recovery(self):
        stop, frames = Stop(), []
        bad = FakeWire([META, ({"kind": "frame", "width": 0, "height": 24}, b"bad")])
        good = FakeWire([META, FRAME])
        connections = deque([bad, good])
        def frame(*value): frames.append(value); stop.set()
        with self.assertLogs("lanbridge.display", level="WARNING"):
            DisplayStream(lambda: connections.popleft(), lambda: (False, [], None), frame,
                          lambda *_: None, stop).run()
        self.assertEqual(len(frames), 1)

    def test_server_keeps_video_alive_when_windows_rejects_input(self):
        stop, activity = Stop(), []
        wire = FakeWire([({"kind": "activity", "active": True}, b""),
                         ({"kind": "move", "u": .5, "v": .5}, b""),
                         ({"kind": "activity", "active": False}, b"")], stop=stop)
        clock = [0.]
        def now(): clock[0] += .1; return clock[0]
        capture = SimpleNamespace(frame=lambda: (b"frame", 32, 24), set_active=activity.append)
        inputs = SimpleNamespace(handle=Mock(side_effect=OSError("blocked")), release=Mock())
        with self.assertLogs("lanbridge.display", level="WARNING"):
            serve_display(wire, capture, inputs, lambda: None, stop, 15, clock=now)
        kinds = [m.get("kind") for m, _ in wire.sent]
        self.assertIn("frame", kinds)
        self.assertIn("input_status", kinds)
        self.assertEqual(activity, [True, False])
        self.assertEqual(wire.owners, {threading.get_ident()})

    def test_server_releases_display_slot_even_when_cleanup_fails(self):
        server = Server.__new__(Server)
        server.config = {}
        server.screen_lock = threading.Lock()
        server.active_displays = set()
        server.input_guard = lambda: True
        server.stopped = Stop()
        server.sessions = SimpleNamespace(check=lambda *_: None)
        capture = SimpleNamespace(monitor={"width": 32}, virtual={}, close=Mock(side_effect=RuntimeError("native cleanup")))
        inputs = SimpleNamespace(release=Mock(side_effect=OSError("blocked")))
        server.screens = SimpleNamespace(Capture=lambda *_: capture, Input=lambda *_: inputs)
        wire = FakeWire([])
        with patch("lanbridge.server.serve_display", side_effect=EOFError()), \
             self.assertLogs("lanbridge.server", level="WARNING"):
            with self.assertRaises(EOFError):
                server.handle_display(wire, {"monitor": 1, "session": "test"})
        self.assertEqual(server.active_displays, set())
        capture.close.assert_called_once()


class ConnectionGraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.agent = Agent.__new__(Agent)
        self.agent.state = Path(self.temp.name)
        self.agent.connection_lost_at = None
        self.agent.reconnect_grace = 30
        self.agent.viewers = SimpleNamespace(stop=Mock())
        self.agent.session_lock = threading.Lock()
        self.agent.connected = threading.Event()
        (self.agent.state / "session.json").write_text("{}")
    def tearDown(self): self.temp.cleanup()

    def test_brief_disconnect_keeps_windows_and_session(self):
        self.assertFalse(self.agent.expire_disconnected_views(100))
        self.assertFalse(self.agent.expire_disconnected_views(120))
        self.agent.viewers.stop.assert_not_called()
        self.assertTrue((self.agent.state / "session.json").exists())

    def test_confirmed_offline_closes_owned_windows(self):
        self.agent.expire_disconnected_views(100)
        self.assertTrue(self.agent.expire_disconnected_views(131))
        self.agent.viewers.stop.assert_called_once()
        self.assertFalse((self.agent.state / "session.json").exists())

    def test_recovery_before_expiry_preserves_recovered_session_and_windows(self):
        self.agent.expire_disconnected_views(100)
        self.agent.connected.set()
        self.assertFalse(self.agent.expire_disconnected_views(131))
        self.agent.viewers.stop.assert_not_called()
        self.assertTrue((self.agent.state / "session.json").exists())

    def test_local_desktop_error_does_not_reset_peer_session(self):
        self.agent.viewers.reconcile = Mock(side_effect=RuntimeError("local desktop"))
        self.agent.update_audio = Mock()
        self.agent.connected = threading.Event()
        self.agent.connected.set()
        with self.assertLogs("lanbridge.agent", level="WARNING"):
            self.agent.update_desktop({"displays": []})
        self.assertTrue(self.agent.connected.is_set())
        self.agent.viewers.stop.assert_not_called()


class CapturePowerTests(unittest.TestCase):
    def test_sleep_inhibition_is_scoped_to_active_view_and_cleared(self):
        capture = Capture.__new__(Capture)
        capture.active = False
        capture.power = SimpleNamespace(SetThreadExecutionState=Mock(return_value=1))
        capture.set_active(True)
        capture.set_active(True)
        capture.set_active(False)
        calls = [call.args[0] for call in capture.power.SetThreadExecutionState.call_args_list]
        self.assertEqual(calls, [0x80000003, 0x80000000])

    def test_capture_resources_close_even_if_sleep_reset_fails(self):
        capture = Capture.__new__(Capture)
        capture.capture = SimpleNamespace(close=Mock())
        capture.set_active = Mock(side_effect=OSError("native failure"))
        with self.assertRaises(OSError):
            capture.close()
        capture.capture.close.assert_called_once()
