# Native acceptance — record actual results on both machines

Portable tests do not prove native desktop behavior. Do these checks in ordinary
logged-in desktop sessions, after installing the same source revision. Mark each
pass/fail/not-tested and keep the existing connection's backup ready. Do not collect
private clipboard text, input logs, personal screenshots or certificates with keys.

## Startup and pairing

1. Confirm both machine addresses against `pairing.json`. Confirm Windows uses the
   already-approved certificate, Linux's public fingerprint is authorized in Windows,
   and the TCP listener exists only once. Verify the Windows hook build hash manifest.
2. Confirm Windows runs one `Lan Bridge` interactive task and one guarded `lan-mouse`
   child. Disable old duplicate Lan Mouse tasks/Run/Startup entries. The process must
   run as the actual desktop user. Windows logon after a reboot must start it again.
3. Confirm Windows firewall TCP/UDP 4242 rules accept only the paired Linux address
   on the Private home network. No broad firewall disable or router forwarding.
4. Activate Linux from its native terminal. `hyprctl configerrors` must be empty;
   `systemctl --user is-active lan-bridge.service lan-mouse.service` must report both
   active. Existing keyboard/mouse sharing must continue when Windows views are idle.
5. Both panels/status must say connected. With a wrong server pin or unapproved
   client certificate, connection must fail before any clipboard/files are sent.

## Workspaces and input

6. Confirm two Windows displays/bounds/DPI in Windows `doctor`. Identify which one is
   screen 1/2 for this backend. Confirm `hyprctl -j clients` shows classes
   `local.lanbridge.screen1/2` on 6/7. If actual GTK app IDs differ, fix the integration
   to match real IDs and rerun native config validation; do not use floating windows.
7. Start from local workspace 2. Connect: the two tiles must appear silently, without
   changing focus or hiding/minimizing any local app. Sidebar entries 6/7 should appear.
8. Click 6 or press Super+6: see Windows display 1. Click 7 or Super+7: see display 2.
   Move the pointer to all four corners of each image and confirm mapping. Test the
   current physical display layout, unequal DPI, and negative virtual-desktop origins.
   Clicking letterbox borders must not click an unrelated point on Windows.
9. On each view test left/right/middle click, drag and release outside the image,
   two-finger/mouse-wheel scroll, typing, uppercase, Ctrl+C/V, Alt+Tab, extended arrows,
   Home/End and Delete. Super+1..7 must remain local; Windows Start must open remotely.
10. Repeat input using **the physical keyboard/mouse attached to Windows while they
    are shared to Linux through Lan Mouse**. There must be no echo, acceleration loop,
    stuck modifiers, blocked replay or pointer jump. This is the critical hook guard
    test, beyond testing only the laptop's built-in keyboard/touchpad.
11. While holding a key/button, switch to a local workspace, close a view, disconnect
    the cable/Wi-Fi, or turn sharing off. Windows must release keys/buttons. Local
    input must remain usable; emergency Lan Mouse release is all four left modifiers.
12. Briefly interrupt the stream: its GTK window stays open with a reconnect indicator.
    After a confirmed 30-second peer outage, owned views close and empty 6/7 disappear
    after focus returns to the last local workspace. Sharing off closes them immediately.
    Unrelated local apps never move or reappear. Reconnect
    creates only the two views; changing display resolution/hotplug should refresh them.
13. Put a local test app in 6 before connecting: the app remains untouched and the
    panel reports the blocked remote workspace; 7 can still work. Remove it to permit
    the view. Put an extra local app next to an already-running view: disconnect must
    close only the viewer and retain that local app and workspace.

## Clipboard, files and sync

14. Copy harmless Unicode text/newlines Linux→Windows and Windows→Linux, then a small
    test PNG each way. Confirm normal Windows DIB/PNG clipboard formats paste in a
    native app. Copy a deliberately marked private item: it must not transfer. There
    must be no repeated clipboard notifications or loop. Turning clipboard off on
    either side must stop clipboard exchange without stopping input.
15. Explicitly send a small file each way from the panels, then an empty file, a file
    spanning many chunks and repeated filenames. Compare SHA-256, verify Inbox paths
    and unique collisions. Disconnect mid-transfer: no partial final file should be
    visible; retry must succeed. Original source files must be retained. Canceling a
    queued offer removes only queue metadata, not the source or already-received file.
16. Use only disposable test files in `Lan Bridge Shared`. Create/edit on each side,
    then edit the same file differently while disconnected. Reconnect: both versions
    must survive and converge; conflict copies should be visible on both machines.
17. Delete a previously synced test file: the counterpart must move to
    `.lanbridge-trash`, recoverable. Test concurrent delete/edit: the edited version
    must survive. A renamed folder should converge without losing data. Symlinks,
    reparse points, traversal paths and case collisions must be rejected safely.
18. Turn sync off and confirm no changes propagate; turn it on to resume. No existing
    personal folders should be scanned. Unchanged Shared files should not be fully
    rehashed each cycle; active large transfers must not interrupt heartbeat or input.

## Audio, lifecycle and limits

19. Play a harmless test sound on Windows with audio enabled on both sides. Audio
    should play only while a remote view is focused, stop on local workspaces/off,
    and resume cleanly. Verify no microphone capture. Test switching Windows default
    output device; failures must not stop clipboard/input or flood the logs.
20. Linux sidebar off→on→off→on must work repeatedly, including after a disabled unit
    has been unloaded. Off stops input, streams, clipboard/sync and login startup;
    on restores correction, startup and the retained peer approval. Test after sleep,
    both OS reboots, temporary Wi-Fi loss, and closing the Windows panel (the companion
    must remain running when only the panel closes).
21. Check CPU/network use while both views are inactive: no desktop frames or audio
    should stream. Check a normal desktop app at the current capture settings. Treat
    fast games, relative mouse, elevated/secure/DRM desktops, HDR and protected content
    as explicitly unsupported/unvalidated unless a backend change is separately tested.
22. Verify Linux rollback and Windows uninstall remove only this integration, preserve
    private identities/Shared/Inbox files, and allow the original Lan Mouse app to run.

Return source commit, exact test results, relevant diagnostics and unresolved failures
in WINDOWS_RESULT.md. Do not mark native checks passed merely because installation,
portable tests or a process launch succeeded.
