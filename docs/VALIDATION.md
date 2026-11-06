# Validation record — 2026-11-04

Performed in the Linux agent's restricted process namespace:

- Portable stdlib unit and in-memory integration suite: **41 tests passed**.
  Tests use real implementation handlers, not replacement feature
  implementations. They cover framing fragmentation/bounds, actual mutual TLS 1.3
  encryption and unapproved-certificate rejection, session lease/revocation, path
  confinement and symlink/case safety, verified atomic file commits, Inbox collisions,
  bidirectional multi-chunk/empty transfers, initial/concurrent sync conflicts,
  deletion recovery and offline edit survival, clipboard hashes/echo prevention,
  extended keys, HiDPI letterboxing and negative monitor origins.
- Python compilation passed for package and native installer/build scripts.
- Installed GTK4 typelib includes the Picture content-fit, FileDialog and texture
  decoding APIs used by the native viewer/panel.
- The actual existing Lan Mouse identity loads successfully into the TLS client
  context after handling its PRIVATE_KEY envelope. Its original file is unchanged.
- Current installed Omarchy workspace widget and Super+6/7 bindings were inspected;
  they already support dynamic workspaces above 5. Official Hyprland 0.56 Lua rule
  documentation was checked before generating the isolated integration module.
- The existing Linux keyboard relay's **11 offline self-tests also passed**.
  The working Linux keyboard relay and whole-sharing controller are included as
  source. No new active Hyprland/sidebar/input settings were changed during staging.

Not performed here:

- Native TCP/UDP/Wayland/systemd integration, GUI focus/rendering, actual input
  injection, network throughput, audio playback or desktop activation. Host desktop
  sockets are inaccessible from this namespace; local network socket operations are
  also restricted. Tests therefore use SSL MemoryBIO and in-memory streams, without
  claiming real network or desktop acceptance.
- Windows dependency installation, Rust/MSVC compilation, Win32 capture/clipboard/
  input/DPI/audio/task/firewall behavior, or cross-machine tests. No Windows session
  is connected to this agent. The Windows handoff contains the full implementation,
  build/install code and explicit native acceptance checklist.
- GitHub CI has not run: this is a local repository and bundle, not a published remote.
- Low-latency game streaming is not validated. The shipped JPEG backend's limits are
  explicit in README.md and must not be described as Sunshine/Moonlight performance.

Native completion is tracked through docs/ACCEPTANCE.md and WINDOWS_RESULT.md, not
inferred from these portable results. The generated handoff manifest identifies the
exact source revision to deploy on both devices.

## Public source preparation — 2026-11-05

- **47 portable tests passed**, including six publication privacy tests. Those tests
  verify that removed secrets are still detected in older Git commits, network/device
  identifiers and private artifacts are rejected, and unreviewed files block a push.
- Python compilation and Git whitespace checks passed after removing owner-specific
  names and generalizing the installation documentation/widget namespace.
- Public publication uses a separate, new Git history with a project-only identity.
  Machine pairing exports, handoff archives, private development history, runtime data
  and actual device details are excluded. See docs/PUBLICATION.md for the audit rules.
- Native Windows/desktop acceptance remains pending as described above.

## Linux activation fixes — 2026-11-05

- **52 portable tests passed** after fixing the Hyprland Lua require namespace and
  Python viewer module discovery from service working directories.
- The generated Lua module was compiled and loaded using a configuration-root search
  path, registering two tiled, silent workspace rules. This verifies Lua module loading;
  native Hyprland reload/config-error checks are still performed during activation.
- Activation preserves a running input engine on first setup, repairs legacy module
  blocks, reports service-bus errors clearly, and waits for fresh connection status
  rather than reporting a stale previous run as connected.

## Stream recovery fixes — 0.1.1

- **62 portable tests passed**. New coverage injects EOF and malformed frames, retries
  a busy display, checks one TLS owner per connection, preserves windows during brief
  control failures, expires them after a confirmed outage, isolates local desktop
  errors and Windows input rejection, and verifies cleanup even when native release
  operations fail. Thread-scoped Windows sleep-inhibition flags are checked with a
  fake native API, including release on inactivity and capture cleanup.
- The previous viewers silently quit on any stream exception, while a single failed
  control check closed both viewer processes. The replacement logs safe error codes,
  reconnects without quitting GTK, and adds a 30-second control recovery interval.
- Shared TLS read/write threads were removed from the Linux display client and
  Windows display server according to OpenSSL's object thread-safety requirements.
- A live peer outage was observed on both the input and feature channels. Its cause
  on Windows/the network is not established by the portable tests. This update does
  not claim that unavailable Windows hardware can be reached or restarted remotely.
- Native end-to-end validation after deploying 0.1.1 remains required. The agent's
  isolated session cannot restart the desktop user service directly.

## Linux client optimizations — 0.1.2

- **80 portable tests passed**; package, scripts and tests compiled, and Git whitespace
  checks passed. The additional client cases exercise the original Windows message
  set and expired-session response, without requiring a server update.
- An integration test blocks both the clipboard and desktop workers while the real
  dedicated heartbeat worker continues renewing. Transport retries retain the current
  session; an explicit expiry permits a new hello. Shutdown/expiry publication races
  and a clipboard request unblocking after off are covered.
- Stream tests cover quiet connections, idle packets without active video, a brief
  stall recovering in place, a prolonged stall reconnecting, normal inactive streams
  and repeated identical frames. A partial message is bounded by one read deadline.
- Render scheduling tests coalesce 100 frame changes or concurrent requests into one
  pending callback, and preserve a frame arriving during the current draw. These
  establish bounded scheduling work, not a measured battery/CPU/latency improvement.
- Protocol remains 1. Windows server/capture/input behavior and private pairing/input
  settings are unchanged. Native client acceptance against the actual older Windows
  companion, GUI behavior and performance measurements remain pending deployment.

## Linux remote touchpad scrolling — 0.1.3

- **94 portable tests passed**, including 14 scroll cases. Package, scripts and tests
  compiled, and Git whitespace checks passed. The installed GTK 4.24.1 exposes the
  scroll-unit API used to distinguish surface pixels from wheel clicks.
- The conversion defaults to 60 logical pixels per wheel click, preserves small
  sub-unit movement and both axes/directions, keeps normal wheel events unchanged,
  validates finite numbers, and bounds extreme input without retaining a backlog.
- Tests exercise the actual viewer scroll callback with a stub GTK application,
  including focus/view-only filtering and fraction resets on focus loss/reconnect.
  Converted messages run through the unchanged Windows input handler and generate
  the expected native wheel units. No Windows update or protocol change is required.
- Actual two-finger scroll feel on the paired machines remains a native check after
  deployment. Local desktop input configuration and pointer/click handling are outside
  the scope of this application-only correction.

## Initial preview and focus recovery — 0.1.4

- **99 portable tests passed**; package/scripts/tests compiled and Git whitespace
  checks passed. Four new startup regression cases failed against 0.1.3 before the
  correction, then passed after it. A fifth protects paused background decoding.
- Tests verify initial preview requests without focus, first-frame redraw/decode,
  recovery from a missed initial focus notification, background pause after the
  preview, and suppression of unfocused keyboard/pointer input during that preview.
  Existing inactive-stream tests now include the expected single initial preview.
- The live 0.1.3 service was connected with two running viewers, but existing logs
  did not distinguish idle streams, received frames and decoded frames. New logs
  cover those stages using categories, dimensions and byte counts only.
- The native GTK codec smoke check could not complete inside the restricted agent
  namespace because its D-Bus-backed loader was denied access. Native window drawing,
  JPEG decoding on the host and the user's actual blank-screen cause remain checks
  to perform after deploying this revision; portable tests do not establish them.
- Protocol remains 1 and no Windows deployment or desktop/input configuration change
  is required for the Linux client correction.
