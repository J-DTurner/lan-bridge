import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit-public.py"
spec = importlib.util.spec_from_file_location("public_auditor", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class PublicationTests(unittest.TestCase):
    def test_machine_network_identifiers_are_blocked(self):
        address = ".".join(("192", "0", "2", "7"))
        self.assertIn("nonlocal IP address", audit.scan_text(address))
        v6 = ":".join(("2001", "db8", "0", "0", "0", "0", "0", "7"))
        self.assertIn("nonlocal IP address", audit.scan_text(v6))
        mac = ":".join(("aa", "bb", "cc", "dd", "ee", "ff"))
        self.assertIn("device MAC/fingerprint", audit.scan_text(mac))

    def test_runtime_artifacts_and_real_material_are_blocked(self):
        for name in ("pairing.json", "device.pem", ".env.local", "session.json", "private.bundle", "state/data.txt"):
            self.assertTrue(audit.forbidden_path(name), name)
        certificate = "-----BEGIN " + "CERTIFICATE-----\n" + "A" * 40 + "\n"
        self.assertIn("certificate/key material", audit.scan_text(certificate))
        token = "gh" + "p_" + "A" * 36
        self.assertIn("access token", audit.scan_text(token))

    def test_public_constants_and_private_rules(self):
        self.assertEqual(audit.scan_text("bind " + "0.0.0.0" + " email lan-bridge@localhost"), set())
        self.assertIn("private deny-list match", audit.scan_text("private-device-label", ["private-device-label"]))
        email = "person" + "@" + "example" + ".test"
        self.assertIn("email address", audit.scan_text(email))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="Lan Bridge", GIT_COMMITTER_NAME="Lan Bridge",
                        GIT_AUTHOR_EMAIL="lan-bridge@localhost", GIT_COMMITTER_EMAIL="lan-bridge@localhost")
        self.git("init", "-b", "main")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
                                       cwd=self.root, env=self.env, stderr=subprocess.PIPE)

    def commit(self, value):
        (self.root / "source.txt").write_text(value)
        self.git("add", "source.txt")
        self.git("commit", "-m", "Source snapshot")

    def test_clean_snapshot_passes(self):
        self.commit("Generic source\n")
        report = audit.audit(self.root, snapshot=True)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["commits_checked"], 1)

    def test_deleted_sensitive_content_still_fails_history_audit(self):
        token = "gh" + "p_" + "B" * 36
        self.commit(token)
        self.commit("Clean current source\n")
        report = audit.audit(self.root)
        self.assertFalse(report["passed"])
        self.assertTrue(any("access token" in finding for finding in report["findings"]))

    def test_nonclean_tree_cannot_be_published(self):
        self.commit("Generic source\n")
        (self.root / "unreviewed.txt").write_text("Not committed")
        report = audit.audit(self.root, snapshot=True)
        self.assertFalse(report["passed"])
        self.assertIn("worktree: uncommitted or untracked files", report["findings"])
