"""Opt-in read-only integration checks against an existing local session."""
import json
import os
import subprocess
import sysconfig
import unittest
from pathlib import Path


@unittest.skipUnless(os.environ.get("SKIPPO_LIVE") == "1", "set SKIPPO_LIVE=1 for live reads")
class LiveReads(unittest.TestCase):
    def run_cli(self, *args):
        executable = str(Path(sysconfig.get_path("scripts")) / "skippo")
        result = subprocess.run([executable, "--json", "--no-input", *args], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, "Live read failed; check session and service access.")
        try:
            return json.loads(result.stdout)
        except ValueError:
            self.fail("Live read returned malformed JSON.")

    def test_account_reads(self):
        self.assertTrue(self.run_cli("auth", "status")["authenticated"])
        boats = self.run_cli("boats", "list")
        self.assertIsInstance(boats, list)
        for boat in boats:
            identifier = str(boat["id"])
            self.assertIsInstance(self.run_cli("checklists", "list", "--boat", identifier), list)
            self.assertIsInstance(self.run_cli("events", "list", "--boat", identifier), list)
            self.assertIsInstance(self.run_cli("notes", "list", "--boat", identifier), list)
