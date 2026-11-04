"""Windows Unicode/PNG clipboard, with native privacy exclusion markers."""
import ctypes as C
from ctypes import wintypes as W
import io
from ..clipboard import Clip, MAX_CLIPBOARD


class Clipboard:
    def __init__(self):
        self.user = C.WinDLL("user32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.user.GetClipboardData.argtypes = [W.UINT]
        self.user.GetClipboardData.restype = W.HANDLE
        self.user.SetClipboardData.argtypes = [W.UINT, W.HANDLE]
        self.user.SetClipboardData.restype = W.HANDLE
        self.user.RegisterClipboardFormatW.argtypes = [W.LPCWSTR]
        self.user.OpenClipboard.argtypes = [W.HWND]
        self.user.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
            C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
        self.user.CreateWindowExW.restype = W.HWND
        self.owner = self.user.CreateWindowExW(0, "STATIC", "Lan Bridge Clipboard", 0,
            0, 0, 0, 0, W.HWND(-3), None, None, None)
        if not self.owner:
            raise C.WinError(C.get_last_error())
        self.kernel.GlobalLock.argtypes = [W.HGLOBAL]
        self.kernel.GlobalLock.restype = C.c_void_p
        self.kernel.GlobalUnlock.argtypes = [W.HGLOBAL]
        self.kernel.GlobalSize.argtypes = [W.HGLOBAL]
        self.kernel.GlobalSize.restype = C.c_size_t
        self.kernel.GlobalAlloc.argtypes = [W.UINT, C.c_size_t]
        self.kernel.GlobalAlloc.restype = W.HGLOBAL
        self.kernel.GlobalFree.argtypes = [W.HGLOBAL]
        self.png = self.user.RegisterClipboardFormatW("PNG")
        self.exclude = self.user.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")

    def read(self):
        if not self.user.OpenClipboard(self.owner):
            return None
        try:
            if self.user.IsClipboardFormatAvailable(self.exclude):
                return None
            fmt = (self.png if self.user.IsClipboardFormatAvailable(self.png) else
                   17 if self.user.IsClipboardFormatAvailable(17) else
                   8 if self.user.IsClipboardFormatAvailable(8) else 13)
            handle = self.user.GetClipboardData(fmt)
            if not handle:
                return None
            size = self.kernel.GlobalSize(handle)
            if size > MAX_CLIPBOARD * (2 if fmt == 13 else 1):
                return None
            pointer = self.kernel.GlobalLock(handle)
            if not pointer:
                return None
            try:
                data = C.string_at(pointer, size)
                if fmt == 13:
                    data = data.decode("utf-16-le").split("\0", 1)[0].encode("utf-8")
                elif fmt in (8, 17):
                    from PIL import BmpImagePlugin
                    image = BmpImagePlugin.DibImageFile(io.BytesIO(data))
                    out = io.BytesIO()
                    image.save(out, format="PNG")
                    data = out.getvalue()
                if len(data) > MAX_CLIPBOARD:
                    return None
                return Clip("text/plain;charset=utf-8" if fmt == 13 else "image/png", data)
            finally:
                self.kernel.GlobalUnlock(handle)
        finally:
            self.user.CloseClipboard()

    def write(self, clip):
        data = clip.data if clip.mime == "image/png" else clip.data.decode("utf-8").encode("utf-16-le") + b"\0\0"
        if not self.user.OpenClipboard(self.owner):
            raise OSError("Clipboard is temporarily busy")
        memory = None
        try:
            memory = self.kernel.GlobalAlloc(0x42, len(data))
            pointer = self.kernel.GlobalLock(memory)
            if not pointer:
                raise C.WinError(C.get_last_error())
            C.memmove(pointer, data, len(data))
            self.kernel.GlobalUnlock(memory)
            if not self.user.EmptyClipboard() or not self.user.SetClipboardData(self.png if clip.mime == "image/png" else 13, memory):
                raise C.WinError(C.get_last_error())
            memory = None  # ownership transferred to Windows
            if clip.mime == "image/png":
                from PIL import Image
                bitmap = io.BytesIO()
                Image.open(io.BytesIO(clip.data)).convert("RGB").save(bitmap, format="BMP")
                dib = bitmap.getvalue()[14:]
                memory = self.kernel.GlobalAlloc(0x42, len(dib))
                pointer = self.kernel.GlobalLock(memory)
                if not pointer:
                    raise C.WinError(C.get_last_error())
                C.memmove(pointer, dib, len(dib))
                self.kernel.GlobalUnlock(memory)
                if not self.user.SetClipboardData(8, memory):
                    raise C.WinError(C.get_last_error())
                memory = None
        finally:
            if memory:
                self.kernel.GlobalFree(memory)
            self.user.CloseClipboard()
