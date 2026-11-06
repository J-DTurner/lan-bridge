"""Client-only recovery against the original protocol, without native desktops."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lanbridge.agent import Agent
from lanbridge.display import CoalescedCall, DisplayStream
from lanbridge.wire import Client, ProtocolError, Wire
from test_display import FakeWire, Stop, META, FRAME
from test_core import MemoryStream, frames


class ClientWatchdogTests(unittest.TestCase):
    def test_brief_video_stall_recovers_without_replacing_connection(self):
        stop, clock, states = Stop(), [0.], []
        wire = FakeWire([META] + [({"kind": "idle"}, b"")] * 3 + [FRAME])
        connect = Mock(return_value=wire)
        def controls(): clock[0] += 1; return True, [], None
        DisplayStream(connect, controls, lambda *_: stop.set(),
                      lambda state, _: states.append(state), stop, clock=lambda: clock[0]).run()
        self.assertIn("stalled", states)
        self.assertEqual(states.count("connected"), 2)
        self.assertNotIn("reconnecting", states)
        connect.assert_called_once()

    def test_original_idle_packets_without_active_video_trigger_in_place_recovery(self):
        stop, clock, states, frames_seen = Stop(), [0.], [], []
        frozen = FakeWire([META] + [({"kind": "idle"}, b"")] * 20)
        healthy = FakeWire([META, FRAME])
        connections = deque([frozen, healthy])
        def controls():
            clock[0] += 1
            return True, [{"kind": "key", "code": 30, "down": True}], None
        def frame(*value):
            frames_seen.append(value)
            stop.set()
        with self.assertLogs("lanbridge.display", level="WARNING") as logs:
            DisplayStream(lambda: connections.popleft(), controls, frame,
                          lambda state, _: states.append(state), stop, clock=lambda: clock[0]).run()
        self.assertIn("stalled", states)
        self.assertIn("reconnecting", states)
        self.assertIn("FRAME_STALLED", " ".join(logs.output))
        self.assertEqual(len(frames_seen), 1)
        self.assertTrue(frozen.closed and healthy.closed)
        # Recovery uses only messages accepted by the original Windows input loop.
        self.assertTrue(all(m["kind"] in {"activity", "release", "key"} for m, _ in frozen.sent))
        release = next(i for i, (m, _) in enumerate(frozen.sent) if m["kind"] == "release")
        self.assertFalse(any(m["kind"] == "key" for m, _ in frozen.sent[release + 1:]))

    def test_static_desktop_frames_are_progress_even_when_pixels_repeat(self):
        stop, clock, states, count = Stop(), [0.], [], [0]
        wire = FakeWire([META] + [FRAME] * 12)
        def controls(): clock[0] += 1; return True, [], None
        def frame(*_):
            count[0] += 1
            if count[0] == 12: stop.set()
        DisplayStream(lambda: wire, controls, frame, lambda state, _: states.append(state),
                      stop, clock=lambda: clock[0]).run()
        self.assertEqual(count[0], 12)
        self.assertNotIn("stalled", states)
        self.assertNotIn("reconnecting", states)

    def test_inactive_original_idle_stream_needs_no_more_frames_after_preview(self):
        stop, clock, states = Stop(), [0.], []
        wire = FakeWire([META, FRAME] + [({"kind": "idle"}, b"")] * 21)
        received = []
        def controls():
            clock[0] += 1
            if clock[0] >= 20: stop.set()
            return False, [], None
        DisplayStream(lambda: wire, controls, lambda *frame: received.append(frame),
                      lambda state, _: states.append(state), stop, clock=lambda: clock[0]).run()
        self.assertEqual(len(received), 1)
        self.assertNotIn("stalled", states)
        self.assertNotIn("reconnecting", states)

    def test_completely_silent_inactive_stream_is_reconnected(self):
        stop, clock, states = Stop(), [0.], []
        class Silent(FakeWire):
            def readable(self, timeout): return bool(self.packets)
        first = Silent([META, FRAME])
        second = FakeWire([META, FRAME])
        wires = deque([first, second])
        def controls(): clock[0] += 2; return False, [], None
        with self.assertLogs("lanbridge.display", level="WARNING"):
            DisplayStream(lambda: wires.popleft(), controls, lambda *_: stop.set() if first.closed else None,
                          lambda state, _: states.append(state), stop, clock=lambda: clock[0]).run()
        self.assertIn("reconnecting", states)
        self.assertTrue(first.closed)


class RenderSchedulingTests(unittest.TestCase):
    def test_concurrent_frame_and_status_requests_share_one_gui_callback(self):
        scheduled = []
        redraw = CoalescedCall(scheduled.append, lambda: None)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: redraw.request(), range(100)))
        self.assertEqual(len(scheduled), 1)
        self.assertFalse(scheduled.pop()())

    def test_burst_queues_one_draw_of_the_newest_frame(self):
        scheduled, rendered, latest = [], [], [None]
        redraw = CoalescedCall(scheduled.append, lambda: rendered.append(latest[0]))
        for number in range(100):
            latest[0] = number
            redraw.request()
        self.assertEqual(len(scheduled), 1)
        self.assertFalse(scheduled.pop()())
        self.assertEqual(rendered, [99])
        self.assertEqual(scheduled, [])

    def test_frame_arriving_during_a_draw_schedules_one_followup(self):
        scheduled, calls = [], []
        def draw():
            calls.append(1)
            if len(calls) == 1:
                redraw.request()
                redraw.request()
        redraw = CoalescedCall(scheduled.append, draw)
        redraw.request()
        scheduled.pop(0)()
        self.assertEqual(len(scheduled), 1)
        scheduled.pop(0)()
        self.assertEqual(len(calls), 2)
        self.assertEqual(scheduled, [])


class FrameDeadlineTests(unittest.TestCase):
    def test_slow_partial_frame_has_one_deadline_and_restores_socket_timeout(self):
        clock = [0.]
        class Slow(MemoryStream):
            timeout = 12
            def recv(self, size):
                clock[0] += .4
                return super().recv(size)
            def gettimeout(self): return self.timeout
            def settimeout(self, value): self.timeout = value
        stream = Slow(frames(({"kind": "frame"}, b"synthetic" * 40)), fragment=8)
        with patch("lanbridge.wire.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                Wire(stream).recv(timeout=2)
        self.assertEqual(stream.timeout, 12)
        self.assertLess(clock[0], 3)

    def test_client_timeouts_do_not_become_new_protocol_fields(self):
        client = Client.__new__(Client)
        client.config = {"host": "127.0.0.1", "port": 4242, "peer_fingerprint": "test"}
        client.session = "test-session"
        raw, secure = Mock(), Mock()
        client.context = SimpleNamespace(wrap_socket=Mock(return_value=secure))
        with patch("lanbridge.wire.socket.create_connection", return_value=raw) as connect, \
             patch("lanbridge.wire.verify_peer"):
            client.connect("display", monitor=1, connect_timeout=3, timeout=3)
        self.assertEqual(connect.call_args.kwargs["timeout"], 3)
        packet = secure.sendall.call_args.args[0]
        header_size, payload_size = struct.unpack("!II", packet[:8])
        self.assertEqual(json.loads(packet[8:8 + header_size]),
                         {"protocol": 1, "op": "display", "session": "test-session", "monitor": 1})
        self.assertEqual(payload_size, 0)


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.agent = Agent.__new__(Agent)
        self.agent.state = Path(self.temp.name)
        self.agent.stopped = threading.Event()
        self.agent.session_lock = threading.Lock()
        self.agent.published_session = None
        self.agent.connected = threading.Event()
        self.agent.client = SimpleNamespace(session="original", call=Mock())

    def tearDown(self): self.temp.cleanup()

    def test_transport_retry_preserves_session_used_by_existing_viewers(self):
        self.agent.client.call.side_effect = [TimeoutError(), ({"displays": []}, b"")]
        with self.assertRaises(TimeoutError): self.agent.heartbeat()
        self.assertEqual(self.agent.client.session, "original")
        self.assertEqual(self.agent.heartbeat(), {"displays": []})
        self.assertEqual([c.args[0] for c in self.agent.client.call.call_args_list], ["heartbeat", "heartbeat"])

    def test_other_protocol_rejection_does_not_trigger_session_rotation(self):
        self.agent.client.call.side_effect = ProtocolError("Incompatible protocol")
        with self.assertRaises(ProtocolError): self.agent.heartbeat()
        self.assertEqual(self.agent.client.session, "original")

    def test_original_companion_expired_session_gets_a_new_hello(self):
        self.agent.client.call.side_effect = [ProtocolError("No active approved sharing session"),
            ({"session": "renewed", "version": "0.1.0"}, b""), ({"displays": []}, b"")]
        with self.assertRaises(ProtocolError): self.agent.heartbeat()
        self.assertIsNone(self.agent.client.session)
        self.agent.heartbeat()
        self.assertEqual(self.agent.peer_version, "0.1.0")
        self.assertEqual(self.agent.client.session, "renewed")
        self.assertEqual([c.args[0] for c in self.agent.client.call.call_args_list], ["heartbeat", "hello", "heartbeat"])

    def test_heartbeat_publishes_session_only_after_successful_renewal(self):
        self.agent.client.session = None
        self.agent.client.call.side_effect = [({"session": "legacy", "version": "0.1.0"}, b""),
                                              ({"displays": []}, b"")]
        def wait(_): self.agent.stopped.set(); return True
        with patch.object(self.agent.stopped, "wait", side_effect=wait):
            self.agent.heartbeats()
        self.assertTrue(self.agent.connected.is_set())
        self.assertEqual(json.loads((self.agent.state / "session.json").read_text())["session"], "legacy")

    def test_shutdown_during_hello_does_not_recreate_session_file(self):
        self.agent.client.session = None
        def hello(*args, **kwargs):
            self.agent.stopped.set()
            return {"session": "stopped"}, b""
        self.agent.client.call.side_effect = hello
        with self.assertRaises(InterruptedError): self.agent.heartbeat()
        self.assertFalse((self.agent.state / "session.json").exists())

    def test_clipboard_that_unblocks_after_off_is_not_transmitted(self):
        self.agent.config = {"clipboard": True}
        def changed():
            self.agent.stopped.set()
            return SimpleNamespace(message=lambda: {"data": "disposable test"})
        self.agent.clipboard = SimpleNamespace(changed=changed)
        self.agent.exchange_clipboard({"clipboard": True})
        self.agent.client.call.assert_not_called()

    def test_slow_clipboard_and_desktop_do_not_block_real_heartbeat_worker(self):
        release, clipboard_busy, desktop_busy, renewed = (threading.Event() for _ in range(4))
        count = [0]
        caps = {"clipboard": True, "displays": [], "audio": False}
        client = SimpleNamespace(session=None)
        def call(op, **kwargs):
            if op == "hello": return {"session": "legacy", "version": "0.1.0"}, b""
            if op == "heartbeat":
                count[0] += 1
                if count[0] >= 2 and clipboard_busy.is_set() and desktop_busy.is_set(): renewed.set()
                return caps, b""
            if op == "clipboard_get":
                clipboard_busy.set()
                release.wait(5)
                return {"clip": None}, b""
            return {"offers": []}, b""
        client.call = call
        def reconcile(_): desktop_busy.set(); release.wait(5)
        viewers = SimpleNamespace(reconcile=reconcile, snapshot=lambda: {}, blocked=[], stop=lambda: None)
        config = {"shared": str(self.agent.state / "shared"), "inbox": str(self.agent.state / "inbox"),
                  "clipboard": True, "sync": False, "audio": False}
        with patch("lanbridge.agent.state_dir", return_value=self.agent.state), \
             patch("lanbridge.agent.Client", return_value=client), \
             patch("lanbridge.agent.Viewers", return_value=viewers), \
             patch("lanbridge.agent.load", return_value=config):
            agent = Agent(self.agent.state / "unused.json", config,
                          SimpleNamespace(read=lambda: None, write=lambda clip: None))
            agent.update_audio = lambda _: None
            runner = threading.Thread(target=agent.run)
            runner.start()
            try:
                self.assertTrue(renewed.wait(4), "Heartbeat did not renew while both optional workers were blocked")
                self.assertFalse(release.is_set())
            finally:
                agent.stopped.set()
                release.set()
                runner.join(2)
            self.assertFalse(runner.is_alive())
