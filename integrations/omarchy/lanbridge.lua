-- Lan Bridge viewers are ordinary tiles. No fullscreen or persistent workspaces.
-- Hyprland 0.56 Lua API; see docs/ARCHITECTURE.md for the official reference.
o.window("^local\\.lanbridge\\.screen1$", {
  workspace = "6 silent",
  tile = true,
  no_initial_focus = true,
})
o.window("^local\\.lanbridge\\.screen2$", {
  workspace = "7 silent",
  tile = true,
  no_initial_focus = true,
})
