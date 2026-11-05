# Update both machines to 0.1.1

This fixes disappearing remote workspaces and several stream recovery problems.
Protocol version remains 1. Existing certificates, peer approval, firewall rules and
the guarded Lan Mouse binary remain compatible. No Rust rebuild or new pairing is needed.

## Linux

Stage this revision from the public checkout, then restart the user service from
the native desktop terminal:

```sh
python scripts/install-linux.py --stage
systemctl --user restart lan-bridge.service
~/.local/bin/lan-bridge status
```

The status should show version 0.1.1. It includes viewer process IDs/running state,
so it is possible to distinguish a failed stream from a closed viewer window.
The source update does not require another Hyprland config edit or reload.

## Windows

Run these commands in the existing installed Git checkout, as its normal desktop
user. Keep the computer awake and reachable while updating. Save any local source
modifications first; do not discard an agent's uncommitted Windows fixes.

```powershell
.\.venv\Scripts\python.exe .\lan-bridge.py off
git pull --ff-only
.\.venv\Scripts\python.exe -m compileall -q lanbridge
.\.venv\Scripts\python.exe .\lan-bridge.py on
.\.venv\Scripts\python.exe .\lan-bridge.py doctor
```

Allow the old task/process to stop before turning it back on; inspect the task if
the companion reports another instance is still running. If the checkout has no
Git remote, apply the matching source update while stopped, retaining `.venv`,
`vendor/bin` and `%LOCALAPPDATA%\LanBridge`. Do not overwrite device configuration.

The Windows changes are needed as well as the Linux update: the display server now
uses one TLS owner, releases a display slot even after a cleanup error, leaves video
running when a protected window rejects SendInput, and inhibits idle sleep only
while a remote display is actively viewed.

## Verify recovery

1. Keep both computers awake. Open 6 and 7, move between them and local workspaces,
   and leave each visible for at least one minute. Viewer process IDs should remain
   stable. A brief stream failure should show a reconnect message in the same window.
2. Restart the Windows companion while Linux sharing remains on. If it returns
   within 30 seconds, the existing viewer windows should recover. A longer confirmed
   outage should close them; reconnecting should recreate them.
3. Turn Linux sharing off: owned views must close promptly. Re-enable it and confirm
   existing keyboard correction and peer approval remain in place.
4. Test ordinary windows and then a protected/elevated window. Windows may reject
   synthetic input there; that must not close video or leave a display permanently busy.
5. Confirm active viewing prevents automatic idle sleep, and leaving remote views
   releases the temporary request. Explicit user sleep must still work normally.

Private logs are `~/.local/state/lan-bridge/display-1.log`, `display-2.log` and
`agent.log` on Linux, and `%LOCALAPPDATA%\LanBridge\state\agent.log` on Windows.
They record error categories, not frames or input contents. Redact device details
before sharing broader diagnostics. Do not publish pairing exports or machine reports.
