from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codex_sync_desktop.core.git_client import command_environment, run


class GitClientEnvironmentTests(unittest.TestCase):
    def test_macos_gui_environment_adds_homebrew_paths(self):
        env = command_environment(
            {"PATH": os.pathsep.join(("/usr/bin", "/bin"))},
            platform_name="darwin",
        )
        entries = env["PATH"].split(os.pathsep)
        self.assertEqual(entries[:3], ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"])
        self.assertEqual(entries[3:], ["/usr/bin", "/bin"])

    def test_macos_gui_environment_deduplicates_paths(self):
        env = command_environment(
            {"PATH": os.pathsep.join(("/usr/local/bin", "/usr/bin", "/opt/homebrew/bin"))},
            platform_name="darwin",
        )
        entries = env["PATH"].split(os.pathsep)
        self.assertEqual(entries.count("/usr/local/bin"), 1)
        self.assertEqual(entries.count("/opt/homebrew/bin"), 1)

    def test_non_macos_environment_is_unchanged(self):
        original_path = os.pathsep.join(("/usr/bin", "/bin"))
        env = command_environment({"PATH": original_path}, platform_name="linux")
        self.assertEqual(env["PATH"], original_path)

    @patch("codex_sync_desktop.core.git_client.subprocess.run")
    @patch("codex_sync_desktop.core.git_client.sys.platform", "darwin")
    @patch.dict(os.environ, {"PATH": os.pathsep.join(("/usr/bin", "/bin"))}, clear=True)
    def test_run_passes_augmented_path_to_git_and_hooks(self, mocked_run):
        mocked_run.return_value = SimpleNamespace(stdout="", stderr="", returncode=0)

        result = run(["git", "push"], Path("/tmp/vault"))

        self.assertTrue(result.ok)
        child_env = mocked_run.call_args.kwargs["env"]
        expected_prefix = os.pathsep.join(("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", ""))
        self.assertTrue(child_env["PATH"].startswith(expected_prefix))


if __name__ == "__main__":
    unittest.main()
