# Lan Bridge

One app for an Omarchy laptop and its paired Windows computer: existing Lan Mouse
keyboard/mouse sharing, shared text/PNG clipboard, sending files either way, automatic
sync of a dedicated Shared folder, and interactive views of two Windows displays.

**Windows display 1 opens as a normal tile on workspace 6; display 2 opens on 7.**
The existing Super+6/Super+7 bindings and numbered sidebar entries work normally.
Viewers are created while connected and closed on disconnect. Local workspaces and
apps are never hidden or minimized. Existing apps in 6/7 are left alone; their remote
view waits until that workspace is free. Windows apps continue to run on Windows.

This is a new 0.1 implementation, prepared for deployment and native acceptance
testing on a paired Linux/Windows setup. Portable protocol/file/sync/crypto tests run on Linux.
Windows capture/input/audio, the Rust engine build, live desktop activation and
cross-machine behavior still require the Windows agent and native test checklist.
Do not describe those native checks as passed until they actually pass.

## Start here

- **Windows agent:** [WINDOWS_AGENT_START_HERE.md](WINDOWS_AGENT_START_HERE.md).
- **Linux setup:** [docs/LINUX_SETUP.md](docs/LINUX_SETUP.md).
- **Native tests:** [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md).
- **Design and protocol:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- **Validation record:** [docs/VALIDATION.md](docs/VALIDATION.md).

The public repository contains source, build scripts and generic installation guides.
Generate `pairing.json` locally and send it privately to the paired machine. It contains
device certificates, fingerprints and LAN addresses and must stay outside source control.
Private offline handoffs can include source and a Git bundle alongside that separate
pairing file. Never upload a machine handoff ZIP or bundle as a public release asset.

## Daily use after activation

Left-click the existing keyboard/sharing sidebar icon to turn the whole suite on/off.
Right-click it for the Lan Bridge panel, file sending, received files, and per-feature
switches. Sharing on also enables desktop-login startup; off disables it. Approval
of the existing peer certificate is retained. Windows has the same Lan Bridge panel
in its Start menu and one interactive logon task that owns its input engine.

Copy text or a PNG image normally to share it. Marked sensitive clipboard items are
skipped; clipboard contents and input events are never written to logs. File sending
requires explicitly selecting a file. Received files go into `Downloads/Lan Bridge
Inbox`; a repeated name gets a new filename. There is no arbitrary remote file browsing
or remote command execution endpoint.

Automatic sync is restricted to `~/Lan Bridge Shared` on each computer. It preserves
concurrent edits as conflict copies; overwritten/deleted versions are moved into that
folder's `.lanbridge-trash` for recovery. Trash is not automatically purged. No existing
Documents, Downloads, Steam or browser data is enrolled in sync. It is a file sync,
so use ordinary closed files; a live database or game actively writing saves needs
application-specific coordination before putting it there.

## Streaming scope

The first backend sends JPEG desktop frames at up to 15 fps by default, with optional
Windows system audio. Inactive views pause capture and audio stops outside the remote
workspaces. Input includes common keyboard keys, buttons and scroll, with letterbox/
HiDPI/negative-monitor-coordinate handling. Super remains local; the viewer's Windows
Start control sends a remote Windows-key tap.

This backend can show game windows but is **not a validated low-latency gaming stream**.
It has no hardware H.264/AV1 encoding, HDR, gamepad or raw relative mouse mode. Games,
exclusive fullscreen, DRM-protected surfaces and anti-cheat can reject capture or
synthetic input. The integration is structured so a faster stream backend can replace
capture without changing pairing, workspaces, files or the single switch.

## Development and updates

Python 3.11+ for the portable core; Python 3.13 is the Windows CI target. Linux uses
the system GTK4/PyGObject, wl-clipboard, ffplay and existing Lan Mouse installation.
Windows dependencies are pinned in `requirements-windows.txt`; Rust/MSVC are needed
to build the small, pinned GPL input-engine patch.

```sh
python -m unittest discover -s tests -v
python -m compileall -q lanbridge scripts
```

The GitHub workflow supplies privacy checks, portable checks on Linux/Windows and a
Windows engine build artifact. Consult the repository's Actions results for current
CI status. Future updates must deploy the same compatible revision to
both machines, then repeat `docs/ACCEPTANCE.md`. Private runtime files stay out of Git.

Public source is published from a reviewed snapshot with neutral commit metadata;
private development history and machine handoffs are not pushed. See
[docs/PUBLICATION.md](docs/PUBLICATION.md) for the audit and publication commands.

GPL-3.0-or-later. See LICENSE and THIRD_PARTY_NOTICES.md.
