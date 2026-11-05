# Linux activation and rollback

The current integration expects an existing paired Lan Mouse engine and sidebar
module at `~/.config/omarchy/bar/modules/LanMouseKeyboard.qml`. It reuses those and
retains the process-specific keyboard relay. Built-in keyboard, pointer settings,
window shelf and unrelated Hyprland settings are preserved. If the sidebar module
does not exist, integrate the supplied generic QML through the local bar layout first.

Staging command:

```sh
python scripts/install-linux.py --stage --host WINDOWS_LAN_IP
```

Staging installs a snapshot under `~/.local/share/lan-bridge/app`, launchers under
`~/.local/bin`, a private `~/.config/lan-bridge/config.json`, and desktop menu entries.
It does **not** edit active Hyprland rules, the sidebar or current Lan Mouse startup.
The `lan-bridge` and `lan-bridge-activate` commands work without a pip environment.

The generated Lua block requires `hypr.lanbridge`, matching Omarchy's configuration
root search path. Older `require("lanbridge")` blocks are replaced on activation.
Viewer children use the installed application directory and an absolute config path,
so starting the service from a home directory does not break Python module discovery.

Run activation in the **native desktop terminal**:

```sh
~/.local/bin/lan-bridge-activate
```

Activation must run in the native desktop session where the user systemd/Hyprland
sockets are accessible. There is no need to restart the Hyprland session; the native
activation script performs the config reload and validation itself.

Activation checks existing config errors first, backs up every changed file under
`~/.local/state/lan-bridge/backups`, adds only a dedicated viewer-rule module, reloads
Hyprland, and checks `hyprctl configerrors`. Failure restores the prior files and input
startup. It then enables `lan-bridge.service` as the single login owner, with the
existing corrected `lan-mouse.service` as its dependency. Off stops both. The existing
sidebar path is reused to avoid Quickshell's cached-QML filename problem. A right-click
opens the native control panel. Legacy keyboard/sharing aliases delegate to the suite.
First activation starts the bridge without unnecessarily restarting an already-running
input engine. The installer then reports the actual Windows feature connection status.

The Windows companion must be installed for the extra channel to connect. Until then
the existing keyboard/mouse engine can continue working and the panel reports waiting.
The remote views appear only for available displays, and never take over workspaces
already occupied by unrelated applications. Move those apps out of 6/7 to allow a view.

Inspect:

```sh
~/.local/bin/lan-bridge doctor
~/.local/bin/lan-bridge status
journalctl --user -u lan-bridge.service -u lan-mouse.service -n 60 --no-pager
hyprctl configerrors
```

Private runtime state, queues, baseline and rotated diagnostic log live under
`~/.local/state/lan-bridge`. `session.json` contains an expiring internal session token;
do not attach it to a bug report. `doctor` omits it and all key/clipboard data, but
does include machine addresses and public fingerprints. Redact those, account names
and device details before posting diagnostics publicly.

Rollback after successful activation:

```sh
python3 ~/.local/share/lan-bridge/app/scripts/rollback-linux.py
```

Rollback removes only the marked require block from the current main Hyprland config
and restores the backed-up files/startup. It retains Shared/Inbox files and the existing
identity. Backups should be reviewed if unrelated edits were made to the same generated
sidebar or unit files after activation. No Omarchy packaged files are modified.

To deploy a later revision, stage it again and run native activation again. Deploy the
same protocol-compatible revision to Windows. If DHCP changes either LAN address, update
the private Linux host / Windows host config and the narrow Windows firewall rule;
prefer DHCP reservations for these two devices. Never rotate identity just to fix an IP.
