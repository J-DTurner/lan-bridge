# Windows agent: install and verify Lan Bridge

Deploy one integrated companion for input, clipboard, file sync and desktop
streaming. Implement/deploy the matching code in this repository
on the existing paired Windows PC. The two physical Windows displays must be
interactive views on the Linux laptop's existing Hyprland workspaces **6 and 7**.
The current Lan Mouse input connection and Linux Alt/Windows correction must keep
working. This handoff is implementation work, not an instruction to stop at research.

Read AGENTS.md, README.md, docs/ARCHITECTURE.md and docs/ACCEPTANCE.md first.
Obtain a **separate, private** `pairing.json` from the Linux installation. Pairing
contains machine-specific certificates, fingerprints and LAN addresses. It is not
included in the public repository and must never be committed or attached to an issue.

## Establish the same source revision

Clone the repository into a permanent project directory. If using a private offline
handoff instead, clone its source bundle:

```powershell
git clone .\lan-bridge.bundle LanBridge
Set-Location .\LanBridge
git log -1 --oneline
```

Keep `pairing.json` outside the clone. For a private offline handoff,
`HANDOFF.json`/`SHA256SUMS.txt` identify its source commit and package hashes.
The GitHub source and private pairing data are distributed separately.

## Preserve the working connection before migration

1. Inventory the active Windows account, OS/architecture, Python, Git, Rust/MSVC,
   installed Lan Mouse version, its executable/config paths, current process,
   scheduled tasks, HKCU Run entries, Startup shortcuts, network profile, firewall,
   and both physical monitor bounds/scaling. Do not expose private keys or clipboard.
2. The existing identity should be `%LOCALAPPDATA%\lan-mouse\lan-mouse.pem` under
   **the actual logged-in desktop user**. Check its certificate SHA-256 against
   `expected_windows_fingerprint` in `pairing.json`. Do not generate a replacement.
   If it differs, find the identity used by the working process before changing
   trust on either machine. The installer intentionally refuses mismatches.
3. Back up existing config and startup registration. Keep all existing Lan Mouse
   clients and authorized peers. The input engine still uses UDP 4242 and the same
   config/identity. Disable duplicate independent Lan Mouse startup registrations
   when migrating; the new companion owns one patched engine process.

## Build and install

Use a normal interactive desktop session, **not a SYSTEM service in Session 0**.
Python 3.13, Git and Rust stable with the Visual Studio C++ Build Tools are expected.
Resolve missing build prerequisites using official packages. Existing native Python
versions >=3.11 can also be evaluated against the pinned dependencies.

```powershell
.\scripts\install-windows.ps1 -PairingFile ..\pairing.json -BuildEngine
```

Use your approved PowerShell process execution policy if local script execution is
restricted; do not permanently lower system policy. Build failures are real pending
work to fix, not a reason to silently switch to an unguarded input engine.

The build pins Lan Mouse v0.11.0 to commit
`0d2190e787db9e482e17d4c16fb7c00ef4841bcb`, verifies the reviewed hook source hash,
applies the supplied Windows capture guard, and builds without GTK. Replay events
carry `dwExtraInfo=0x4C424749`; both mouse and keyboard hooks pass those events through
to Windows applications without transmitting them back to Linux. The pointer origin
is updated on marked moves to avoid a jump on the next physical mouse event.
The executable hash manifest gates interactive viewing. Never fake that manifest
for a stock binary. A view-only mode without an engine exists for development only.

The installer preserves the identity and TOML clients/trust, adds the Linux public
fingerprint if absent, creates a single limited interactive logon task named
`Lan Bridge`, and starts it. The Start menu gets one Lan Bridge control panel.
Application state is under `%LOCALAPPDATA%\LanBridge`, restricted to the user/SYSTEM.

Configure the firewall in an **Administrator PowerShell for that same account**:

```powershell
.\scripts\configure-firewall.ps1 -PairingFile ..\pairing.json
```

This allows inbound TCP 4242 for the new TLS feature channel and UDP 4242 for the
input engine, from the exact paired Linux address, on Private networks. It deliberately
avoids executable-path rules, which break with Python's virtual-environment launcher.
Verify the actual home connection profile is Private and Linux's address is current.
Do not disable the firewall, add Public-profile rules or router port forwarding.
The Linux client connects outbound; no new Linux inbound TCP rule is needed.

## Verify and finish the Windows implementation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe .\lan-bridge.py doctor
Get-ScheduledTaskInfo -TaskName 'Lan Bridge'
Get-NetTCPConnection -LocalPort 4242 -State Listen
Get-NetUDPEndpoint -LocalPort 4242
Get-Content "$env:LOCALAPPDATA\LanBridge\state\agent.log" -Tail 50
```

Do not run another foreground companion while the task already owns TCP 4242.
Use `lan-bridge.py off` to stop gracefully before debugging `windows-agent` in the
foreground. The off/on controls also disable/enable this user's logon startup.

Complete **every applicable native check in docs/ACCEPTANCE.md** with the laptop.
If capture, ctypes ABI, clipboard ownership, audio loopback, scheduling, hook
compilation, scaling or input routing fails on the actual Windows version, debug
and fix the implementation, rerun portable tests, and return a patch/commit.
Native acceptance must include input originating from both the laptop and the
Windows-connected physical keyboard/mouse, because the latter exercises the loop guard.

After staging the Linux installation, run in its native desktop terminal:

```sh
~/.local/bin/lan-bridge-activate
```

That enables the integrated sidebar and validates Hyprland rules with rollback.
Remote views must open silently on 6/7, pause when inactive, and close on disconnect.
Do not add fullscreen/minimize/restore logic or alter existing laptop pointer speed.

Keep a private `WINDOWS_RESULT.md` with the exact commit, Python/dependency versions, built
engine hash, monitor IDs/bounds/scaling, actual LAN addresses, task/firewall status,
test outputs, and each acceptance result marked pass/fail/not-tested. Include precise
remaining issues and any source patch/bundle needed on Linux. Redact LAN addresses,
account names, device identifiers and fingerprints before sharing diagnostics publicly.
Never include private keys, clipboard payloads, personal transferred files or session tokens. A report of
"installed" without communication and input/workspace testing is incomplete.
