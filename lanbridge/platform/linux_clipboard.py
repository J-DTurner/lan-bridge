import subprocess
from ..clipboard import Clip, MAX_CLIPBOARD


class Clipboard:
    def read(self):
        try:
            types = subprocess.run(["wl-paste", "--list-types"], capture_output=True, timeout=0.8).stdout.decode().splitlines()
            if any("passwordmanagerhint" in t.lower() or "secret" in t.lower() for t in types):
                return None
            mime = "image/png" if "image/png" in types else next((t for t in types if t.startswith("text/plain")), None)
            if not mime:
                return None
            data = subprocess.run(["wl-paste", "--no-newline", "--type", mime], capture_output=True, timeout=1)
            if data.returncode or len(data.stdout) > MAX_CLIPBOARD:
                return None
            return Clip("image/png" if mime == "image/png" else "text/plain;charset=utf-8", data.stdout)
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            return None

    def write(self, clip):
        subprocess.run(["wl-copy", "--type", clip.mime], input=clip.data, check=True, timeout=3)
