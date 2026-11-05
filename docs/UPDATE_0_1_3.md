# Linux remote touchpad scrolling — 0.1.3

GTK reports touchpad scrolling in surface pixels and mouse-wheel scrolling in wheel
clicks. The Linux viewer previously forwarded both unchanged as protocol wheel clicks,
greatly amplifying surface scrolling. The correction runs only in the Linux viewer.
Windows 0.1.0 and 0.1.1 understand the resulting existing scroll messages; no Windows
update or protocol/pairing change is required.

- Surface motion defaults to one wheel click per 60 logical pixels, for both axes.
- Fractional movement accumulates until it reaches one native Windows wheel unit,
  avoiding loss of tiny gestures when the older receiver rounds to integers.
- Mouse-wheel deltas retain their original units within the existing protocol bounds.
- Fractional remainders reset between gestures, on focus loss and on reconnect.
- Only the focused, interactive viewer forwards scrolling. Local desktop scroll
  settings, pointer movement, physical click handling and Windows settings are untouched.

The optional Linux application setting `touchpad_scroll_pixels_per_step` defaults to
60. Larger values make streamed touchpad scrolling slower. The allowed range is 1
through 10000; this setting applies only to surface-unit events in remote viewers.
It is not a Hyprland input setting, and existing configs use the default automatically.

Stage the updated checkout, then restart from the normal desktop terminal:

```sh
python3 scripts/install-linux.py --stage
systemctl --user restart lan-bridge.service
lan-bridge status
```

Check version 0.1.3 and test a modest two-finger swipe on both 6 and 7, horizontal
scrolling, a direction reversal and several tiny movements. Compare an ordinary
mouse-wheel click in the same remote app. Switch to a local workspace and confirm
its scrolling/click behavior still matches your existing settings. Screen/app-specific
scroll feel still needs a native check on the paired machines.
