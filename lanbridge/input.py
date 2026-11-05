"""Portable coordinate, key and scroll translation, testable off Windows."""
from __future__ import annotations
import math
from .wire import ProtocolError

INJECT_MARKER = 0x4C424749
EXTENDED = {96: 0xE01C, 97: 0xE01D, 98: 0xE035, 99: 0xE037,
            100: 0xE038, 102: 0xE047, 103: 0xE048, 104: 0xE049,
            105: 0xE04B, 106: 0xE04D, 107: 0xE04F, 108: 0xE050,
            109: 0xE051, 110: 0xE052, 111: 0xE053,
            125: 0xE05B, 126: 0xE05C, 127: 0xE05D}


class ScrollNormalizer:
    """Convert GTK surface pixels into the existing protocol's wheel clicks."""
    def __init__(self, pixels_per_step=60):
        if (type(pixels_per_step) not in (int, float) or
            not math.isfinite(pixels_per_step) or not 1 <= pixels_per_step <= 10000):
            raise ValueError("touchpad_scroll_pixels_per_step must be between 1 and 10000")
        self.pixels_per_step = pixels_per_step
        self.reset()

    def reset(self):
        self.remainder = [0., 0.]

    def convert(self, dx, dy, *, surface):
        if not all(type(value) in (int, float) and math.isfinite(value) for value in (dx, dy)):
            raise ValueError("Scroll deltas must be finite numbers")
        if not surface:
            self.reset()
            values = [max(-100, min(100, value)) for value in (dx, dy)]
        else:
            values = []
            for axis, delta in enumerate((dx, dy)):
                # Preserve movement below one native Windows wheel unit rather
                # than rounding each small touchpad event away at the receiver.
                limit = 100 * self.pixels_per_step
                limited = max(-limit, min(limit, delta))
                units = self.remainder[axis] + limited * (120 / self.pixels_per_step)
                whole = math.trunc(units)
                self.remainder[axis] = units - whole
                # Keep the original protocol bounds and drop any excessive
                # packet immediately, without retaining a scrolling backlog.
                values.append(max(-12000, min(12000, whole)) / 120)
        if not any(values):
            return None
        return {"kind": "scroll", "dx": values[0], "dy": values[1]}


def windows_scancode(evdev: int) -> int | None:
    if type(evdev) is not int:
        return None
    return evdev if 1 <= evdev <= 83 or evdev in (86, 87, 88) else EXTENDED.get(evdev)


def normalized_point(x, y, view_width, view_height, image_width, image_height):
    if min(view_width, view_height, image_width, image_height) <= 0:
        return None
    scale = min(view_width / image_width, view_height / image_height)
    width, height = image_width * scale, image_height * scale
    left, top = (view_width - width) / 2, (view_height - height) / 2
    if not left <= x <= left + width or not top <= y <= top + height:
        return None
    return (min(1., max(0., (x - left) / width)), min(1., max(0., (y - top) / height)))


def absolute_point(monitor: dict, virtual: dict, u: float, v: float):
    if not all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in (u, v)):
        raise ProtocolError("Invalid pointer coordinate")
    x = monitor["left"] + round(u * (monitor["width"] - 1))
    y = monitor["top"] + round(v * (monitor["height"] - 1))
    return (round((x - virtual["left"]) * 65535 / max(1, virtual["width"] - 1)),
            round((y - virtual["top"]) * 65535 / max(1, virtual["height"] - 1)))
