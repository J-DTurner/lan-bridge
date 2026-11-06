# Initial display preview and focus recovery — 0.1.4

This Linux-only update addresses a startup path where the companion is connected
and viewer windows exist, but no image is requested or painted until keyboard focus
arrives. Silent workspace placement deliberately avoids initial focus, so preview
delivery must not depend on that focus.

- Every new display connection requests one video preview using the original
  activity message. Once a frame arrives, unfocused streams return to idle.
- The Linux window paints its first frame while unfocused. Later background frames
  remain coalesced for the next focus rather than continuously decoding.
- The viewer initializes its draw scheduler before presenting the window, samples
  initial GTK focus after presentation, and resynchronizes focus when drawing.
- Preview activity permits video only: keyboard and pointer events still require
  the focused view. Local apps and workspace/window rules remain unchanged.
- Private logs record stream connection, video/focus transitions, first-frame
  dimensions/byte count and first successful decode. Frames and input contents
  are never logged.

Protocol remains 1, using messages accepted by Windows 0.1.0 and 0.1.1. Windows does
not need an update. A black frame captured on Windows, a locked Windows session or
a native rendering problem still requires separate diagnosis; the added stage logs
distinguish those paths from absence of received/decoded frames.

## Apply

```sh
python3 scripts/install-linux.py --stage
systemctl --user restart lan-bridge.service
lan-bridge status
```

Run the restart in the actual Linux desktop terminal. Confirm Linux version 0.1.4.
No Hyprland reload or input setting changes are needed for this application update.

## Verify

1. Keep Windows awake and unlocked. Reconnect from a local workspace: initial
   previews should arrive without stealing focus or starting ongoing background video.
2. Open 6 and 7 and click inside each view. Confirm live video/input, then switch
   back to a local workspace and confirm capture pauses again.
3. In each `display-1.log`/`display-2.log`, check for `Display stream connected`,
   `First video frame received` and `First video frame decoded`.
4. If all three stages succeed but the image still appears black, inspect Windows
   session/capture state and native rendering. Do not treat control-channel connection
   alone as proof that the video pipeline works.
