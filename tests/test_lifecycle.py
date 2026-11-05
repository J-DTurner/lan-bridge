from pathlib import Path
from types import SimpleNamespace
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from lanbridge import control
from lanbridge.workspaces import Viewers
from lanbridge.agent import Agent
from lanbridge.clipboard import ClipboardLink, Clip
from lanbridge.wire import ProtocolError
from lanbridge import __version__


class Child:
    def __init__(self): self.code = None; self.stopped = False
    def poll(self): return self.code
    def terminate(self): self.stopped = True; self.code = 0
    def kill(self): self.stopped = True; self.code = -9
    def wait(self, timeout=None): return self.code


class WorkspaceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.viewers = Viewers(Path("config.json"), {"workspaces": [6, 7]})
        self.displays = [{"id": 1, "left": 0, "top": 0, "width": 1920, "height": 1080},
                         {"id": 2, "left": 1920, "top": 0, "width": 2560, "height": 1440}]

    def test_occupied_workspace_left_alone_other_view_can_open(self):
        clients = [{"workspace": {"id": 6}, "class": "steam"}]
        with patch("lanbridge.workspaces.hypr_json", side_effect=[{"id": 2}, clients]), \
             patch("lanbridge.workspaces.subprocess.Popen", return_value=Child()) as start:
            self.viewers.reconcile(self.displays)
        self.assertEqual(self.viewers.blocked, [6])
        self.assertEqual(set(self.viewers.children), {2})
        self.assertEqual(start.call_args.args[0][-1], "2")
        self.assertEqual(self.viewers.last_local, 2)

    def test_disconnect_only_stops_owned_process_and_retains_local_neighbor(self):
        child = Child()
        self.viewers.children[1] = child
        clients = [{"workspace": {"id": 6}, "class": "steam"}]
        with patch("lanbridge.workspaces.hypr_json", side_effect=[{"id": 6}, clients]), \
             patch("lanbridge.workspaces.subprocess.run") as dispatch:
            self.viewers.stop()
        self.assertTrue(child.stopped)
        self.assertEqual(self.viewers.children, {})
        dispatch.assert_not_called()

    def test_empty_remote_workspace_returns_to_last_local_on_disconnect(self):
        self.viewers.children[1] = Child()
        self.viewers.last_local = 4
        clients = [{"workspace": {"id": 6}, "class": "local.lanbridge.screen1"}]
        with patch("lanbridge.workspaces.hypr_json", side_effect=[{"id": 6}, clients]), \
             patch("lanbridge.workspaces.subprocess.run") as dispatch:
            self.viewers.stop()
        self.assertIn('workspace = "4"', dispatch.call_args.args[0][-1])

    def test_repeated_heartbeat_does_not_duplicate_viewers(self):
        state = {"activeworkspace": {"id": 2}, "clients": []}
        with patch("lanbridge.workspaces.hypr_json", side_effect=lambda key: state[key]), \
             patch("lanbridge.workspaces.subprocess.Popen", side_effect=lambda *a, **kw: Child()) as start:
            self.viewers.reconcile(self.displays)
            self.viewers.reconcile(self.displays)
        self.assertEqual(start.call_count, 2)

    def test_viewer_package_resolves_when_daemon_was_started_outside_project(self):
        state = {"activeworkspace": {"id": 2}, "clients": []}
        with patch("lanbridge.workspaces.hypr_json", side_effect=lambda key: state[key]), \
             patch("lanbridge.workspaces.subprocess.Popen", return_value=Child()) as start:
            self.viewers.reconcile(self.displays[:1])
        # Run the actual child module lookup without opening a graphical window.
        cwd = start.call_args.kwargs["cwd"]
        arguments = start.call_args.args[0]
        self.assertTrue(Path(arguments[arguments.index("--config") + 1]).is_absolute())
        result = subprocess.run([sys.executable, "-m", "lanbridge", "--version"],
                                cwd=cwd, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), __version__)


class SharingControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls = []
        unit = Path(self.temp.name) / ".config/systemd/user/lan-bridge.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("[Service]\n")

    def tearDown(self): self.temp.cleanup()

    def test_on_after_unloaded_disabled_unit_does_not_reset_nonfailed_service(self):
        if __import__("os").name == "nt":
            self.skipTest("Linux systemd lifecycle")
        def systemd(*args, **kwargs):
            self.calls.append(args)
            return SimpleNamespace(returncode=1 if args[0] == "is-failed" else 0)
        with patch.object(control, "state_dir", return_value=Path(self.temp.name)), \
             patch.object(control.Path, "home", return_value=Path(self.temp.name)), \
             patch.object(control, "systemd", side_effect=systemd), \
             patch.object(control.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            control.change("on")
        self.assertFalse(any(c[0] == "reset-failed" for c in self.calls))
        self.assertIn(("enable", "--now", "lan-bridge.service"), self.calls)

    def test_off_stops_input_and_all_integrated_features(self):
        if __import__("os").name == "nt":
            self.skipTest("Linux systemd lifecycle")
        def systemd(*args, **kwargs):
            self.calls.append(args)
            return SimpleNamespace(returncode=0)
        with patch.object(control, "state_dir", return_value=Path(self.temp.name)), \
             patch.object(control.Path, "home", return_value=Path(self.temp.name)), \
             patch.object(control, "systemd", side_effect=systemd), \
             patch.object(control.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            control.change("off")
        self.assertIn(("disable", "--now", "lan-bridge.service"), self.calls)
        self.assertIn(("disable", "--now", "lan-mouse.service"), self.calls)

    def test_staged_on_cannot_disable_working_input_before_activation(self):
        if __import__("os").name == "nt":
            self.skipTest("Linux systemd lifecycle")
        (Path(self.temp.name) / ".config/systemd/user/lan-bridge.service").unlink()
        with patch.object(control.Path, "home", return_value=Path(self.temp.name)), \
             patch.object(control, "systemd") as systemd:
            with self.assertRaisesRegex(RuntimeError, "staged"):
                control.change("on")
        systemd.assert_not_called()


class FeatureIsolationTests(unittest.TestCase):
    def test_busy_clipboard_retries_without_bubbling_into_connection_lifecycle(self):
        clip = Clip("text/plain;charset=utf-8", b"safe test text")
        adapter = SimpleNamespace(read=lambda: clip, write=lambda value: None)
        agent = Agent.__new__(Agent)
        agent.config = {"clipboard": True}
        agent.clipboard = ClipboardLink(adapter)
        calls = []
        def call(op, **kwargs):
            calls.append(op)
            if len(calls) == 1:
                raise ProtocolError("Clipboard temporarily busy")
            return {"clip": None}, b""
        agent.client = SimpleNamespace(call=call)
        with self.assertLogs("lanbridge.agent", level="WARNING"):
            agent.exchange_clipboard({"clipboard": True})
        self.assertIsNone(agent.clipboard.seen)
        agent.exchange_clipboard({"clipboard": True})
        self.assertEqual(calls.count("clipboard_set"), 2)
        self.assertEqual(agent.clipboard.seen, clip.key)
        self.assertIsNone(agent.clipboard_error)
