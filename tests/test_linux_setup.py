import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_linux", ROOT / "scripts/install-linux.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class LinuxSetupTests(unittest.TestCase):
    def test_module_block_is_idempotent_and_repairs_old_namespace(self):
        original = '-- personal settings\nrequire("hypr.input")\n'
        content = installer.add_hyprland_module(original + installer.LEGACY_MARKER)
        self.assertIn(original.strip(), content)
        self.assertIn('require("hypr.lanbridge")', content)
        self.assertNotIn('require("lanbridge")', content)
        self.assertEqual(content.count("-- BEGIN LAN BRIDGE"), 1)
        self.assertEqual(installer.add_hyprland_module(content), content)

    def test_generated_module_loads_with_configuration_root_lua_search_path(self):
        lua = shutil.which("lua")
        if not lua:
            self.skipTest("Lua interpreter unavailable on this test platform")
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)
            (config / "hypr").mkdir()
            shutil.copy2(ROOT / "integrations/omarchy/lanbridge.lua", config / "hypr/lanbridge.lua")
            script = '''
package.path = arg[1] .. "/?.lua;" .. package.path
local rules = {}
o = {window = function(match, rule) rules[#rules + 1] = rule end}
'''+installer.MARKER+'''
assert(#rules == 2)
assert(rules[1].workspace == "6 silent" and rules[1].tile == true)
assert(rules[2].workspace == "7 silent" and rules[2].no_initial_focus == true)
'''
            file = config / "check.lua"
            file.write_text(script)
            subprocess.run([lua, str(file), str(config)], check=True, capture_output=True)

    def test_command_error_explains_native_session_access_failure(self):
        result = subprocess.CompletedProcess(["systemctl"], 1, "", "Failed to connect to user bus: Operation not permitted\n")
        with patch.object(installer.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "Operation not permitted"):
                installer.command("systemctl", "--user", "show-environment")

    def test_connection_wait_rejects_stale_status(self):
        stale = {"updated": 10, "connected": True}
        current = {"updated": 30, "connected": True, "displays": []}
        with patch.object(installer, "read_json", side_effect=[stale, current]), \
             patch.object(installer.time, "sleep") as wait:
            result = installer.wait_for_connection(20, timeout=5)
        self.assertIs(result, current)
        wait.assert_called_once()
