"""A newly connected view must paint a preview before keyboard focus arrives."""
from inspect import getclosurevars
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import test_scroll
from test_display import FakeWire, Stop, META, FRAME
from lanbridge.display import DisplayStream


class ViewerStartupTests(unittest.TestCase):
    def setUp(self):
        fixture = test_scroll.ViewerScrollTests()
        fixture.setUp()
        self.viewer = fixture.viewer
        self.viewer.focused = False
        self.viewer.window = SimpleNamespace(is_active=lambda: False)
        self.viewer.picture = SimpleNamespace(set_paintable=Mock())
        self.viewer.label = SimpleNamespace(set_visible=Mock(), set_label=Mock())
        closure = getclosurevars(self.viewer.render).nonlocals
        closure['Gdk'].Texture = SimpleNamespace(new_from_bytes=Mock(return_value=object()))
        closure['GLib'].Bytes = SimpleNamespace(new=lambda data: data)
        closure['GLib'].Error = type('SyntheticDecodeError', (Exception,), {})

    def test_first_frame_requests_a_draw_without_keyboard_focus(self):
        self.viewer.frame(*FRAME)
        self.viewer.redraw.request.assert_called_once()

    def test_unfocused_first_preview_is_decoded_and_displayed(self):
        self.viewer.frame(*FRAME)
        self.viewer.render()
        self.assertTrue(self.viewer.has_frame)
        self.viewer.picture.set_paintable.assert_called_once()
        self.assertIsNone(self.viewer.latest)

    def test_render_catches_active_window_when_initial_focus_notification_was_missed(self):
        self.viewer.window.is_active = lambda: True
        self.viewer.frame(*FRAME)
        self.viewer.render()
        self.assertTrue(self.viewer.focused)
        self.assertTrue(self.viewer.has_frame)

    def test_background_view_with_a_preview_does_not_keep_decoding_frames(self):
        self.viewer.has_frame = True
        self.viewer.frame(*FRAME)
        self.viewer.render()
        self.viewer.redraw.request.assert_not_called()
        self.viewer.picture.set_paintable.assert_not_called()
        self.assertIsNotNone(self.viewer.latest)


class StreamPreviewTests(unittest.TestCase):
    def test_initial_preview_then_pause_without_forwarding_unfocused_input(self):
        stop, calls, frames = Stop(), [0], []
        wire = FakeWire([META, FRAME, ({'kind': 'idle'}, b'')])
        def controls():
            calls[0] += 1
            if calls[0] >= 2:
                stop.set()
            return False, [{'kind': 'key', 'code': 30, 'down': True}], {'kind': 'move', 'u': .5, 'v': .5}
        DisplayStream(lambda: wire, controls, lambda *frame: frames.append(frame),
                      lambda *_: None, stop).run()
        activity = [m['active'] for m, _ in wire.sent if m.get('kind') == 'activity']
        self.assertEqual(activity, [True, False])
        self.assertEqual(len(frames), 1)
        self.assertFalse(any(m.get('kind') in ('key', 'move') for m, _ in wire.sent))
