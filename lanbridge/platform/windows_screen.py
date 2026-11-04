"""Per-monitor capture and marked Win32 input injection in the logged-in session."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import io
import threading
from ..input import INJECT_MARKER, windows_scancode, absolute_point
from ..wire import ProtocolError


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class UNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", UNION)]


def dpi_aware():
    user = C.WinDLL("user32", use_last_error=True)
    try:
        user.SetProcessDpiAwarenessContext.argtypes = [C.c_void_p]
        user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except AttributeError:
        user.SetProcessDPIAware()


def monitors():
    import mss
    with mss.mss() as capture:
        return [{"id": i, "name": f"Windows display {i}", **dict(m)}
                for i, m in enumerate(capture.monitors) if i > 0]


class Capture:
    def __init__(self, monitor_id, max_width):
        import mss
        self.capture = mss.mss()  # MSS object is created/used on this same thread
        if not 1 <= monitor_id < len(self.capture.monitors):
            raise ProtocolError("Display is no longer connected")
        self.monitor = dict(self.capture.monitors[monitor_id])
        self.virtual = dict(self.capture.monitors[0])
        self.max_width = max(640, min(2560, int(max_width)))

    def frame(self):
        from PIL import Image
        shot = self.capture.grab(self.monitor)
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if image.width > self.max_width:
            image.thumbnail((self.max_width, self.max_width), Image.Resampling.BILINEAR)
        data = io.BytesIO()
        image.save(data, format="JPEG", quality=75, optimize=False)
        return data.getvalue(), image.width, image.height

    def close(self):
        self.capture.close()


class Input:
    def __init__(self, monitor, virtual):
        self.user = C.WinDLL("user32", use_last_error=True)
        self.user.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
        self.user.SendInput.restype = W.UINT
        self.monitor, self.virtual = monitor, virtual
        self.keys, self.buttons = set(), set()
        self.lock = threading.RLock()

    def emit(self, item):
        if self.user.SendInput(1, C.byref(item), C.sizeof(INPUT)) != 1:
            raise OSError("Windows refused input; elevated/secure desktops cannot be controlled")

    def mouse(self, flags, data=0, x=0, y=0):
        item = INPUT(type=0)
        item.mi = MOUSEINPUT(x, y, data & 0xFFFFFFFF, flags, 0, INJECT_MARKER)
        self.emit(item)

    def key(self, code, down):
        scan = windows_scancode(code)
        if scan is None:
            return
        item = INPUT(type=1)
        item.ki = KEYBDINPUT(0, scan & 0xFF, 8 | (1 if scan > 255 else 0) | (0 if down else 2), 0, INJECT_MARKER)
        self.emit(item)
        (self.keys.add if down else self.keys.discard)(code)

    def handle(self, event):
        with self.lock:
            kind = event.get("kind")
            if kind == "move":
                x, y = absolute_point(self.monitor, self.virtual, event.get("u"), event.get("v"))
                self.mouse(0x8000 | 0x4000 | 1, x=x, y=y)
            elif kind == "button":
                button, down = event.get("button"), event.get("down")
                if button not in (1, 2, 3) or type(down) is not bool:
                    raise ProtocolError("Invalid mouse button")
                flags = {1: (2, 4), 2: (0x20, 0x40), 3: (8, 0x10)}[button]
                self.mouse(flags[0 if down else 1])
                (self.buttons.add if down else self.buttons.discard)(button)
            elif kind == "key":
                if type(event.get("down")) is not bool:
                    raise ProtocolError("Invalid key state")
                self.key(event.get("code"), event["down"])
            elif kind == "scroll":
                for axis, flags in (("dy", 0x800), ("dx", 0x1000)):
                    value = event.get(axis, 0)
                    if type(value) not in (int, float) or not -100 <= value <= 100:
                        raise ProtocolError("Invalid scroll delta")
                    if value:
                        self.mouse(flags, round(value * 120) * (-1 if axis == "dy" else 1))
            elif kind == "release":
                self.release()
            else:
                raise ProtocolError("Unsupported input event")

    def release(self):
        with self.lock:
            for code in list(self.keys):
                self.key(code, False)
            for button in list(self.buttons):
                self.handle({"kind": "button", "button": button, "down": False})
