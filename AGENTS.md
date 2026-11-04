# Lan Bridge

One integrated Linux/Windows companion for Lan Mouse input, clipboard, file transfer,
conservative folder sync, and two Windows monitor views in Hyprland workspaces 6/7.

Read README.md and docs/ARCHITECTURE.md before changing behavior. Windows agents
start with WINDOWS_AGENT_START_HERE.md. Never claim native Windows or Hyprland
acceptance tests passed when only portable tests were run.

- Keep the existing Lan Mouse identity and keyboard correction. Never commit PEM
  private keys, clipboard contents, transferred files, runtime configs or pairing.json.
- Never add arbitrary remote command execution. All filesystem operations stay in
  the dedicated Shared/Inbox roots; preserve overwritten/deleted sync files in trash.
- Do not overwrite personal Hyprland input, pointer speed, bindings or existing windows.
- Workspaces 6 and 7 are ordinary tiled GTK viewer windows, created only while paired.
  Do not use fullscreen, floating windows, persistent workspaces or hide local apps.
- Windows injected input must carry the Lan Bridge marker and the pinned Lan Mouse
  capture patch must be installed before enabling interactive remote views.
- Run `python -m unittest discover -s tests -v` and `python -m compileall -q lanbridge`.
  Tests must cover meaningful protocol, sync, path, identity and input behavior.
- Linux changes are applied by scripts/install-linux.py, with backups and native
  `hyprctl reload` / `hyprctl configerrors` validation and rollback.
- Update the Windows handoff and protocol version when compatibility changes.
- Public publication must use a sanitized snapshot and neutral commit metadata.
  Never push private development history, handoff bundles, machine reports or pairing
  files. Run scripts/audit-public.py over every reachable public commit before pushing.
