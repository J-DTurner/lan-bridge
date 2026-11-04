# Design and protocol v1

One user-facing application supervises an existing input engine and a finite set of
extra features. No browser dashboard, cloud service, account, analytics or arbitrary
command execution endpoint is used. Installation/build downloads come from the package
registries and source repositories; runtime connections go to the configured peer.

## Network and identity

- **UDP 4242:** existing Lan Mouse v0.11 input engine, config and certificate trust.
- **TCP 4242:** Windows companion listens; Linux connects out using TLS 1.3. This is
  a new protocol on the same numbered port, not an extra feature of Lan Mouse's UDP
  protocol. Windows accepts only the configured Linux IPv4 address and trusted cert.
- Existing Lan Mouse certificate/private key stays on its original machine. The public
  SHA-256 fingerprint is over the certificate DER, matching upstream `src/crypto.rs`.
  Windows requires the Linux leaf certificate during TLS authentication and pins its
  fingerprint; Linux pins the approved Windows fingerprint before sending any app data.
  Self-signed peer trust is deliberate; hostname PKI validation is not substituted for
  the fingerprint. A different certificate is refused, even at the expected IP.
- `webrtc-dtls` writes the PKCS#8 envelope as `PRIVATE_KEY`; OpenSSL requires `PRIVATE KEY`.
  The loader normalizes that envelope only in a private temporary file, immediately
  removes it after loading the SSL context, and never rewrites or exports the identity.
- `hello` establishes one random session token with a 20-second lease. A separate
  heartbeat worker renews it; all subsequent feature connections require it. Every
  transferred frame rechecks session validity. Off/disconnect revokes it; inactive
  viewers and any held keys/buttons are released. New hello supersedes an old session.

Frames are `uint32 big-endian JSON length`, `uint32 big-endian binary length`, UTF-8
JSON object, then raw binary. Limits: JSON 8 MiB, binary 12 MiB, file chunks 256 KiB,
clipboard 4 MiB, individual files 64 GiB, sync inventory 20,000 files. JSON is data,
never pickle or executable code. TLS connections are independent for short RPCs,
bulk transfer, each screen and optional audio; bulk files cannot block heartbeat/input.
Per-peer listener concurrency is bounded. Each native connection has finite timeouts.

Operation set: hello, heartbeat, disconnect; clipboard_get/set; manifest/delete;
put/get for explicit Inbox, Shared or offer scopes; offers/offer_done; display; audio.
There is no shell, arbitrary URL fetch, arbitrary path read or process-management RPC.

## Files and sync

Sending a file records local metadata only in an owner-private outgoing queue.
Linux sends directly to the Windows Inbox; Windows offers explicitly selected files
and Linux pulls them to its Inbox, so Linux needs no additional listening TCP port.
Inbox collisions get unique filenames. Source/destination checksums and atomic commit
are mandatory. Symlinks/reparse points, traversal, absolute paths, NTFS device names,
alternate streams and case-ambiguous cross-platform merges are rejected.

The dedicated Shared folders use three-way sync with an acknowledged common hash
baseline. Single edits propagate; concurrent changes keep both versions under a
conflict filename. A deletion propagates only relative to the common baseline; edited
survivors win over concurrent deletion. Replaced/deleted files are archived locally
in `.lanbridge-trash`, excluded from sync and never automatically purged. Precondition
hashes stop races from overwriting new local edits. A failed pass does not advance the
baseline; partial work retries. Unchanged files use a stat/hash cache to avoid hashing
the entire Shared folder every 10 seconds. Clipboard feedback uses content hashes.

## Screens, input and desktop integration

Windows uses MSS/Pillow for per-monitor JPEG capture and Win32 SendInput for marked
input. System DPI awareness is set before monitor inventory/capture. Stream coordinates
are normalized through the actual letterboxed GTK image into each physical monitor's
virtual-desktop bounds, including negative origins and different scaling. Common evdev
codes become Windows Set-1 scancodes with extended-key flags. Input is released on
focus loss, socket loss, lease expiry and shutdown. GTK keeps a single newest frame
and a bounded input queue; obsolete pointer moves are coalesced.

The physical Windows input may already be captured by Lan Mouse and forwarded to Linux.
Replaying it from a remote view must not get captured and forwarded a second time.
The pinned Windows hook patch passes events marked `0x4C424749` directly to Windows
applications, updates its pointer origin on marked moves, and respects ncode<0.
The companion verifies the built engine's hash manifest before enabling interaction.
It supervises that engine in the same user's interactive session; no Session-0 service
or privileged global input driver is installed.

Each Linux view is a GTK Wayland application with class `local.lanbridge.screen1/2`.
User-level Hyprland Lua rules assign it to `6 silent` / `7 silent`, `tile=true`,
`no_initial_focus=true`. The stock Omarchy workspace widget already displays existing
workspaces 6/7 and existing Super+6/7 bindings select them. On disconnect, only owned
viewer children close; if needed focus returns to the last local workspace so empty
6/7 can disappear. Occupied local workspaces are not stolen. There are no fullscreen,
floating, shelf/minimize or persistent-workspace changes.

Only the active viewer captures frames. Audio loopback uses SoundCard/Windows WASAPI
and PCM stereo to Linux ffplay while a remote workspace is active and both sides allow
audio. No microphone input is captured. This baseline is desktop streaming, with the
gaming/performance limits documented in README.md.

## Sources checked for this implementation

- [Lan Mouse pinned crypto/fingerprint implementation](https://github.com/feschber/lan-mouse/blob/0d2190e787db9e482e17d4c16fb7c00ef4841bcb/src/crypto.rs)
- [Pinned Windows low-level capture hooks](https://github.com/feschber/lan-mouse/blob/0d2190e787db9e482e17d4c16fb7c00ef4841bcb/input-capture/src/windows/event_thread.rs)
- [Hyprland 0.56 Lua window rules](https://wiki.hypr.land/0.56.0/Configuring/Basics/Window-Rules/)
- [Microsoft SendInput structures](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-input)
- [Microsoft interactive scheduled-task logon type](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype)
- [MSS maintainer package](https://pypi.org/project/mss/), [Pillow](https://pypi.org/project/Pillow/), [SoundCard](https://pypi.org/project/SoundCard/)

Current installed Omarchy helper/window/workspace sources were also inspected read-only;
packaged `/usr/share/omarchy` files are never modified.
