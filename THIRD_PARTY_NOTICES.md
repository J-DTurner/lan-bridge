# Third-party components

Lan Bridge is GPL-3.0-or-later. The original copyright and license of each dependency
remain in force. Dependencies are not silently downloaded by the running application.

- Lan Mouse, Ferdinand Schober and contributors, GPL-3.0-or-later:
  https://github.com/feschber/lan-mouse . Input engine pinned to v0.11.0, commit
  `0d2190e787db9e482e17d4c16fb7c00ef4841bcb`. `patches/windows-event-thread.rs` is a
  modified copy of its `input-capture/src/windows/event_thread.rs`; the original and
  modified SHA-256 values and a unified diff are supplied alongside it. Source is
  fetched from that exact commit by `scripts/build-engine.py`. Any distribution of
  the built executable must include the corresponding source and build instructions.
- The per-process Linux Wayland keyboard relay and prior sharing controller were
  developed for this user's existing setup and are included in `integrations/linux`.
- MSS, MIT: https://github.com/BoboTiG/python-mss .
- Pillow, HPND: https://github.com/python-pillow/Pillow .
- SoundCard, BSD-3-Clause: https://github.com/bastibe/SoundCard .
- Python/stdlib, PSF: https://www.python.org/psf/license/ .
- GTK, GLib, PyGObject, FFmpeg, wl-clipboard and Omarchy remain system dependencies
  governed by their own licenses; their binaries are not bundled here.
