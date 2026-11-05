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
