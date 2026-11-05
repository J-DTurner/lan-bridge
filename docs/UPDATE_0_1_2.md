# Linux client optimizations — 0.1.2

This update can be installed on Linux while Windows remains on 0.1.0 or 0.1.1.
Protocol stays at version 1. Existing Windows dependencies, input engine, pairing,
trust and firewall settings remain usable. Keep any local Windows-agent fixes.

## Changes on Linux

- A dedicated heartbeat worker renews the original 20-second lease every two seconds.
  Slow clipboard, file or Hyprland operations cannot hold it up. Clipboard polling
  runs independently once per second; healthy heartbeat requests are less frequent.
- A failed transport retries the existing token. Only an explicit expired-session
  rejection requests a new hello, avoiding unnecessary invalidation of working views.
- A focused display that stops delivering video shows recovery at three seconds,
  resends the original activity message, and reconnects that stream at six seconds.
  Its GTK window stays open. An inactive stream recovers after ten seconds without
  any packets; normal idle packets are sufficient. Identical frames count as progress.
- Framed reads have a three-second total deadline, including partial messages.
  Display connect/handshake and socket timeouts are three seconds. Control uses a
  three-second connect/handshake timeout and four-second socket timeout.
- GTK renders the newest frame through one coalesced idle callback. There is no
  permanent 33 ms draw timer, no queue of obsolete decodes, and no decoding while a
  view is unfocused. Active input polling is bounded to approximately 60 Hz rather
  than 125 Hz; actual mouse handling remains event-driven.
- Status reports the peer version and last connection-error category without
  recording frames, clipboard contents or input events.

Windows still controls capture FPS, encoding and its own availability. These client
changes improve local scheduling/recovery; native measurements are needed to quantify
CPU, battery and latency gains. Older server implementation defects can still require
a Windows fix. A confirmed 30-second control outage closes owned viewers as before.

## Apply on Linux

From an updated source checkout:

```sh
python3 scripts/install-linux.py --stage
systemctl --user restart lan-bridge.service
lan-bridge status
```

Staging is independent of desktop IPC. Restart from the actual desktop terminal.
No Hyprland config reload is required for these application-only changes. Confirm
Linux status shows `version: 0.1.2`, inspect `peer_version`, and use the additional
checks in [ACCEPTANCE.md](ACCEPTANCE.md#linux-012-with-an-older-windows-companion).

Logs remain in `~/.local/state/lan-bridge/agent.log` and `display-1.log`/`display-2.log`.
The watchdog logs `FRAME_STALLED` as an error category, without screen contents.
