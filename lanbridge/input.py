"""Portable coordinate/key translation, independently testable off Windows."""
from __future__ import annotations
import math
from .wire import ProtocolError

INJECT_MARKER = 0x4C424749
EXTENDED = {96: 0xE01C, 97: 0xE01D, 98: 0xE035, 99: 0xE037,
            100: 0xE038, 102: 0xE047, 103: 0xE048, 104: 0xE049,
            105: 0xE04B, 106: 0xE04D, 107: 0xE04F, 108: 0xE050,
            109: 0xE051, 110: 0xE052, 111: 0xE053,
            125: 0xE05B, 126: 0xE05C, 127: 0xE05D}


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
