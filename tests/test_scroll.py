"""Pixel-to-wheel conversion through the Linux callback and legacy Windows input."""
import math
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lanbridge.input import ScrollNormalizer
from lanbridge.platform.windows_screen import Input
from lanbridge.viewer import run as run_viewer


class ScrollConversionTests(unittest.TestCase):
    def test_surface_distance_becomes_one_wheel_click_per_sixty_pixels(self):
        event = ScrollNormalizer().convert(30, -60, surface=True)
        self.assertEqual(event, {"kind": "scroll", "dx": .5, "dy": -1.})

    def test_wheel_clicks_and_high_resolution_wheel_units_are_preserved(self):
        normalizer = ScrollNormalizer()
        for dx, dy in ((0, 1), (0, -1), (.25, -.5), (2, 3)):
            self.assertEqual(normalizer.convert(dx, dy, surface=False), {"kind": "scroll", "dx": dx, "dy": dy})

    def test_tiny_surface_moves_accumulate_instead_of_disappearing(self):
        normalizer = ScrollNormalizer()
        native = [0, 0]
        for _ in range(100):
            event = normalizer.convert(.1, -.1, surface=True)
            if event:
                native[0] += round(event["dx"] * 120)
                native[1] += round(event["dy"] * 120)
        # Rounding error/remainder may retain less than one native unit.
        self.assertLess(abs(native[0] - 20), 1.01)
        self.assertLess(abs(native[1] + 20), 1.01)
        self.assertEqual(native[0], -native[1])

    def test_gesture_reset_discards_only_subpixel_remainder(self):
        normalizer = ScrollNormalizer()
        self.assertIsNone(normalizer.convert(0, .2, surface=True))
        normalizer.reset()
        self.assertIsNone(normalizer.convert(0, .3, surface=True))

    def test_new_wheel_device_does_not_inherit_a_touchpad_remainder(self):
        normalizer = ScrollNormalizer()
        normalizer.convert(0, .2, surface=True)
        normalizer.convert(0, 1, surface=False)
        self.assertIsNone(normalizer.convert(0, .3, surface=True))

    def test_large_flick_stays_in_protocol_bounds_without_scrolling_backlog(self):
        normalizer = ScrollNormalizer()
        event = normalizer.convert(1e308, -1e308, surface=True)
        self.assertEqual(event["dx"], 100)
        self.assertEqual(event["dy"], -100)
        self.assertIsNone(normalizer.convert(0, 0, surface=True))

    def test_both_axes_keep_direction_and_cancel_reversed_movement(self):
        normalizer = ScrollNormalizer()
        forward = normalizer.convert(60, -120, surface=True)
        reverse = normalizer.convert(-60, 120, surface=True)
        self.assertEqual(forward["dx"], -reverse["dx"])
        self.assertEqual(forward["dy"], -reverse["dy"])

    def test_invalid_values_and_settings_are_rejected(self):
        for setting in (0, -1, True, "60", math.nan, math.inf):
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                ScrollNormalizer(setting)
        for value in (math.nan, math.inf, True, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ScrollNormalizer().convert(value, 0, surface=True)

    def test_configurable_touchpad_factor_does_not_scale_mouse_wheel(self):
        normalizer = ScrollNormalizer(120)
        self.assertEqual(normalizer.convert(0, 60, surface=True)["dy"], .5)
        self.assertEqual(normalizer.convert(0, 1, surface=False)["dy"], 1)

    def test_original_windows_input_consumes_normalized_events_without_update(self):
        receiver = Input.__new__(Input)
        receiver.lock = threading.RLock()
        receiver.mouse = Mock()
        receiver.handle(ScrollNormalizer().convert(60, 60, surface=True))
        self.assertEqual(receiver.mouse.call_args_list[0].args, (0x800, -120))
        self.assertEqual(receiver.mouse.call_args_list[1].args, (0x1000, 120))


class ViewerScrollTests(unittest.TestCase):
    def setUp(self):
        captured = []
        class Application:
            def __init__(self, **kwargs): pass
            def run(self, argv): captured.append(self)
        self.units = SimpleNamespace(SURFACE=1, WHEEL=0)
        repository = SimpleNamespace(Gtk=SimpleNamespace(Application=Application),
            Gdk=SimpleNamespace(ScrollUnit=self.units),
            Gio=SimpleNamespace(ApplicationFlags=SimpleNamespace(NON_UNIQUE=1)), GLib=SimpleNamespace())
        with patch.dict(sys.modules, {"gi": SimpleNamespace(require_version=lambda *_: None), "gi.repository": repository}):
            run_viewer(None, {}, 1)
        self.viewer = captured[0]
        self.active = True
        self.viewer.window = SimpleNamespace(is_active=lambda: self.active)
        self.viewer.redraw = SimpleNamespace(request=Mock())
        self.viewer.interactive = True
        self.surface = SimpleNamespace(get_unit=lambda: self.units.SURFACE)
        self.wheel = SimpleNamespace(get_unit=lambda: self.units.WHEEL)

    def test_actual_viewer_callback_distinguishes_pixels_from_wheel_clicks(self):
        self.assertTrue(self.viewer.scroll(self.surface, 0, 60))
        self.assertEqual(self.viewer.events.get_nowait()["dy"], 1)
        self.assertTrue(self.viewer.scroll(self.wheel, 0, 1))
        self.assertEqual(self.viewer.events.get_nowait()["dy"], 1)

    def test_unfocused_or_view_only_stream_does_not_send_scroll(self):
        self.active = False
        self.assertFalse(self.viewer.scroll(self.surface, 0, 60))
        self.active = True
        self.viewer.interactive = False
        self.assertFalse(self.viewer.scroll(self.surface, 0, 60))
        self.assertTrue(self.viewer.events.empty())

    def test_focus_loss_discards_fractional_scroll_before_next_view(self):
        self.viewer.scroll(self.surface, 0, .2)
        self.active = False
        self.viewer.focus()
        self.assertEqual(self.viewer.events.get_nowait()["kind"], "release")
        self.active = True
        self.viewer.focus()
        self.viewer.scroll(self.surface, 0, .3)
        self.assertTrue(self.viewer.events.empty())

    def test_reconnect_discards_fractional_scroll(self):
        self.viewer.scroll(self.surface, 0, .2)
        self.viewer.stream_state("reconnecting", {})
        self.viewer.stream_state("connected", {"interactive": True})
        self.viewer.scroll(self.surface, 0, .3)
        self.assertTrue(self.viewer.events.empty())
