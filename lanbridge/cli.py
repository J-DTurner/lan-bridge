from __future__ import annotations
import argparse
import importlib.util
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import ssl
import sys
from . import PROTOCOL, __version__
from .config import load, home_dir, state_dir, read_json, atomic_json, certificate_pem, own_fingerprint


def logging_setup():
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = state / "agent.log"
    handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lan-bridge")
    parser.add_argument("--config", type=Path, default=home_dir() / "config.json")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("daemon", "windows-agent", "panel", "status", "doctor", "bar-status", "on", "off", "toggle"):
        sub = commands.add_parser(name)
        if name in ("on", "off", "toggle"):
            sub.add_argument("--notify", action="store_true")
    sub = commands.add_parser("send")
    sub.add_argument("files", nargs="+", type=Path)
    sub = commands.add_parser("view")
    sub.add_argument("--monitor", type=int, choices=(1, 2), required=True)
    sub = commands.add_parser("export-pairing")
    sub.add_argument("--address", required=True)
    sub.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ("on", "off", "toggle", "bar-status"):
            from .control import change, bar_status
            if args.command == "bar-status":
                print(json.dumps(bar_status()))
            else:
                change(args.command)
            return 0
        if args.command == "status":
            print(json.dumps(read_json(state_dir() / "status.json", {"running": False, "connected": False}), indent=2))
            return 0
        config = load(args.config)
        config["config_path"] = str(args.config.resolve())
        if args.command == "export-pairing":
            atomic_json(args.output, {"protocol": PROTOCOL, "linux_address": args.address,
                         "port": config["port"], "linux_fingerprint": own_fingerprint(Path(config["identity"])),
                         "linux_certificate": certificate_pem(Path(config["identity"])),
                         "expected_windows_fingerprint": config["peer_fingerprint"], "workspaces": config["workspaces"]})
            print(f"Public pairing exported to {args.output}; contains no private key")
        elif args.command == "send":
            from .offers import Offers
            for path in args.files:
                print("Queued", Offers(state_dir()).add(path))
        elif args.command == "panel":
            from .panel import run
            run(args.config, config)
        elif args.command == "view":
            from .viewer import run
            run(args.config, config, args.monitor)
        elif args.command == "doctor":
            checks = {"version": __version__, "protocol": PROTOCOL, "platform": sys.platform,
                      "python": sys.version.split()[0], "openssl": ssl.OPENSSL_VERSION,
                      "identity_fingerprint": own_fingerprint(Path(config["identity"])),
                      "approved_peer": config["peer_fingerprint"], "endpoint": f'{config["host"]}:{config["port"]}',
                      "dependencies": {n: importlib.util.find_spec(n) is not None for n in
                          (("mss", "PIL", "soundcard", "tkinter") if os.name == "nt" else ("gi",))},
                      "state": read_json(state_dir() / "status.json", {})}
            if os.name == "nt":
                from .engine import guard_verified
                from .platform.windows_screen import dpi_aware, monitors
                dpi_aware()
                checks["input_guard"] = guard_verified(config)
                checks["monitors"] = monitors()
            print(json.dumps(checks, indent=2))
        elif args.command == "daemon":
            logging_setup()
            from .agent import Agent
            from .platform.linux_clipboard import Clipboard
            agent = Agent(args.config, config, Clipboard())
            signal.signal(signal.SIGTERM, lambda *_: agent.stopped.set())
            signal.signal(signal.SIGINT, lambda *_: agent.stopped.set())
            agent.run()
        elif args.command == "windows-agent":
            if os.name != "nt":
                raise ValueError("The Windows companion must run on Windows")
            logging_setup()
            import ctypes as C
            kernel = C.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = [C.c_void_p, C.c_int, C.c_wchar_p]
            kernel.CreateMutexW.restype = C.c_void_p
            mutex = kernel.CreateMutexW(None, False, "Local\\LanBridgeCompanion")
            if not mutex or C.get_last_error() == 183:
                raise ValueError("Lan Bridge is already running")
            from .engine import Engine
            from .platform import windows_screen
            from .platform.windows_clipboard import Clipboard
            from .server import Server
            windows_screen.dpi_aware()
            engine = Engine(config)
            server = Server(config, Clipboard(), windows_screen)
            signal.signal(signal.SIGINT, lambda *_: server.stopped.set())
            signal.signal(signal.SIGTERM, lambda *_: server.stopped.set())
            import threading
            def watch():
                while not server.stopped.wait(1):
                    try:
                        engine.check()
                    except RuntimeError:
                        server.stopped.set()
            try:
                engine.start()
                threading.Thread(target=watch, daemon=True).start()
                server.serve()
            finally:
                engine.stop()
                kernel.CloseHandle.argtypes = [C.c_void_p]
                kernel.CloseHandle(mutex)
        return 0
    except Exception as exc:
        if args.command in ("daemon", "windows-agent"):
            logging.getLogger(__name__).error("%s stopped: %s", args.command, str(exc))
        print(f"Lan Bridge: {exc}", file=sys.stderr)
        if getattr(args, "notify", False) and os.name != "nt":
            import subprocess
            subprocess.run(["notify-send", "Lan Bridge", "Could not change sharing. Run lan-bridge doctor and check the user service journal."], check=False)
        return 1
