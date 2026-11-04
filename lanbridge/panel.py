"""One native control panel on each OS; no browser dashboard or extra listener."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import threading
from .config import atomic_json, read_json, state_dir
from .offers import Offers


def open_folder(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def summary():
    status = read_json(state_dir() / "status.json", {})
    import time
    fresh = time.time() - status.get("updated", 0) < 8
    if status.get("running") and fresh:
        text = "Windows connected · Displays on workspaces 6 and 7" if status.get("connected") else "Sharing on · Waiting for the other computer"
    else:
        text = "Sharing stopped"
    if status.get("transfer_error"):
        text += "\nA transfer or sync needs attention; see agent.log"
    if status.get("clipboard_error"):
        text += "\nClipboard temporarily unavailable; retrying"
    if status.get("blocked_workspaces"):
        text += "\nMove existing apps out of workspaces " + ", ".join(map(str, status["blocked_workspaces"]))
    return text


def set_feature(config_path, config, name, value):
    config[name] = bool(value)
    current = read_json(config_path)
    current[name] = bool(value)
    atomic_json(config_path, current)


def run(config_path, config):
    if os.name == "nt":
        return windows(config_path, config)
    return linux(config_path, config)


def linux(config_path, config):
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gio, GLib

    class Panel(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="local.lanbridge.panel", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

        def do_activate(self):
            window = self.get_active_window()
            if window:
                window.present()
                return
            window = Gtk.ApplicationWindow(application=self, title="Lan Bridge")
            window.set_default_size(480, 360)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            for name in ("top", "bottom", "start", "end"):
                getattr(box, f"set_margin_{name}")(20)
            self.label = Gtk.Label(label=summary(), wrap=True, xalign=0)
            box.append(self.label)
            buttons = [("Turn sharing on", lambda *_: self.control("on")),
                       ("Turn sharing off", lambda *_: self.control("off")),
                       ("Send a file…", lambda *_: self.choose(window)),
                       ("Cancel queued files", lambda *_: Offers(state_dir()).cancel_all()),
                       ("Open received files", lambda *_: open_folder(config["inbox"])),
                       ("Open Shared folder", lambda *_: open_folder(config["shared"]))]
            for label, callback in buttons:
                button = Gtk.Button(label=label)
                button.connect("clicked", callback)
                box.append(button)
            for name, label in (("clipboard", "Share clipboard"), ("sync", "Sync the dedicated Shared folder"), ("audio", "Play Windows audio while viewing a remote workspace")):
                check = Gtk.CheckButton(label=label)
                check.set_active(config.get(name, False))
                check.connect("toggled", lambda widget, n=name: set_feature(config_path, config, n, widget.get_active()))
                box.append(check)
            window.set_child(box)
            window.present()
            GLib.timeout_add_seconds(2, self.refresh)

        def refresh(self):
            self.label.set_label(summary())
            return True

        def control(self, mode):
            from .control import change
            def job():
                try:
                    change(mode)
                except Exception:
                    GLib.idle_add(self.label.set_label, "Could not change sharing; check lan-bridge doctor and the service journal")
            threading.Thread(target=job, daemon=True).start()

        def choose(self, window):
            dialog = Gtk.FileDialog(title="Send a file to Windows")
            def selected(dialog, result):
                try:
                    file = dialog.open_finish(result)
                    if file and file.get_path():
                        Offers(state_dir()).add(Path(file.get_path()))
                        self.label.set_label("File queued · It will arrive in the Windows Inbox")
                except GLib.Error:
                    pass
                except Exception as exc:
                    self.label.set_label(str(exc))
            dialog.open(window, None, selected)

    Panel().run([])


def windows(config_path, config):
    import tkinter as tk
    from tkinter import filedialog, messagebox
    from .control import change
    root = tk.Tk()
    root.title("Lan Bridge")
    root.geometry("520x440")
    text = tk.StringVar()
    tk.Label(root, textvariable=text, wraplength=480, justify="left").pack(padx=18, pady=18, anchor="w")

    def control(mode):
        try:
            change(mode)
        except Exception as exc:
            messagebox.showerror("Lan Bridge", str(exc))

    def choose():
        path = filedialog.askopenfilename(title="Send a file to the Linux laptop")
        if path:
            try:
                Offers(state_dir()).add(Path(path))
                messagebox.showinfo("Lan Bridge", "File queued for the Linux Inbox")
            except Exception as exc:
                messagebox.showerror("Lan Bridge", str(exc))

    for label, callback in (("Turn sharing on", lambda: control("on")), ("Turn sharing off", lambda: control("off")),
                            ("Send a file…", choose), ("Cancel queued files", lambda: Offers(state_dir()).cancel_all()),
                            ("Open received files", lambda: open_folder(config["inbox"])),
                            ("Open Shared folder", lambda: open_folder(config["shared"]))):
        tk.Button(root, text=label, command=callback).pack(fill="x", padx=18, pady=3)
    for name, label in (("clipboard", "Share clipboard"), ("sync", "Sync the dedicated Shared folder"), ("audio", "Allow Windows system audio streaming")):
        value = tk.BooleanVar(value=config.get(name, False))
        check = tk.Checkbutton(root, text=label, variable=value,
            command=lambda n=name, v=value: set_feature(config_path, config, n, v.get()))
        check.var = value
        check.pack(anchor="w", padx=18, pady=3)

    def refresh():
        status = read_json(state_dir() / "status.json", {})
        import time
        fresh = time.time() - status.get("updated", 0) < 8
        text.set("Linux connected · Displays available as workspaces 6/7" if fresh and status.get("connected") else
                 "Companion running · Waiting for Linux" if fresh and status.get("running") else "Companion stopped")
        root.after(2000, refresh)
    refresh()
    root.mainloop()
