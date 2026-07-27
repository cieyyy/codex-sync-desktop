from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from codex_sync_desktop.core.git_client import CommandResult
from codex_sync_desktop.core.onboarding import (
    create_private_repository,
    github_setup_status,
    select_macos_gh_installer_asset,
    validate_proxy_url,
)


class ProxyValidationTests(TestCase):
    def test_accepts_local_http_proxy(self):
        self.assertEqual(validate_proxy_url(" http://127.0.0.1:7890 "), "http://127.0.0.1:7890")

    def test_rejects_proxy_credentials_and_invalid_scheme(self):
        with self.assertRaises(ValueError):
            validate_proxy_url("http://name:secret@127.0.0.1:7890")
        with self.assertRaises(ValueError):
            validate_proxy_url("socks5://127.0.0.1:7890")


class PrivateRepositorySetupTests(TestCase):
    @patch("codex_sync_desktop.core.onboarding.github_auth_status")
    @patch("codex_sync_desktop.core.onboarding.run")
    def test_resumes_existing_local_clone_of_same_private_repository(self, mocked_run, mocked_auth):
        mocked_auth.return_value = CommandResult(True, "", 0)
        mocked_run.side_effect = [
            CommandResult(True, "git version 2.50", 0),
            CommandResult(True, "gh version 2.75", 0),
            CommandResult(True, json.dumps({"login": "buyer", "id": 123}), 0),
            CommandResult(True, "exists", 0),
            CommandResult(True, json.dumps({"isPrivate": True, "url": "https://github.com/buyer/codex-sync-vault"}), 0),
            CommandResult(True, "credentials ready", 0),
            CommandResult(True, "https://github.com/buyer/codex-sync-vault.git", 0),
            CommandResult(True, "", 0),
            CommandResult(True, "", 0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "codex-sync-vault"
            (target / ".git").mkdir(parents=True)
            result = create_private_repository(target, "codex-sync-vault")

        self.assertEqual(result.local_path, target.resolve())
        commands = [call.args[0] for call in mocked_run.call_args_list]
        self.assertNotIn(["git", "clone", "https://github.com/buyer/codex-sync-vault.git", str(target.resolve())], commands)

    @patch("codex_sync_desktop.core.onboarding.github_auth_status")
    @patch("codex_sync_desktop.core.onboarding.run")
    def test_creates_verifies_and_clones_private_repository(self, mocked_run, mocked_auth):
        mocked_auth.return_value = CommandResult(True, "logged in", 0)
        mocked_run.side_effect = [
            CommandResult(True, "git version 2.50", 0),
            CommandResult(True, "gh version 2.75", 0),
            CommandResult(True, json.dumps({"login": "buyer", "id": 123}), 0),
            CommandResult(False, "not found", 1),
            CommandResult(True, "created", 0),
            CommandResult(True, json.dumps({"isPrivate": True, "url": "https://github.com/buyer/codex-sync-vault", "nameWithOwner": "buyer/codex-sync-vault"}), 0),
            CommandResult(True, "credentials ready", 0),
            CommandResult(True, "cloned", 0),
            CommandResult(True, "", 0),
            CommandResult(True, "", 0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "codex-sync-vault"
            result = create_private_repository(target, "codex-sync-vault", "http://127.0.0.1:7890")

        self.assertEqual(result.owner, "buyer")
        self.assertEqual(result.url, "https://github.com/buyer/codex-sync-vault")
        commands = [call.args[0] for call in mocked_run.call_args_list]
        self.assertIn(["gh", "repo", "create", "buyer/codex-sync-vault", "--private", "--description", "Private Codex conversation sync vault"], commands)
        self.assertLess(commands.index(["gh", "auth", "setup-git"]), commands.index(["git", "clone", "https://github.com/buyer/codex-sync-vault.git", str(target.resolve())]))

    @patch("codex_sync_desktop.core.onboarding.github_auth_status", return_value=CommandResult(True, "", 0))
    @patch("codex_sync_desktop.core.onboarding.run")
    def test_refuses_public_repository(self, mocked_run, _auth):
        mocked_run.side_effect = [
            CommandResult(True, "git version 2.50", 0),
            CommandResult(True, "gh version 2.75", 0),
            CommandResult(True, json.dumps({"login": "buyer", "id": 123}), 0),
            CommandResult(True, "exists", 0),
            CommandResult(True, json.dumps({"isPrivate": False, "url": "https://github.com/buyer/public"}), 0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "不是私有仓库"):
                create_private_repository(Path(directory) / "vault", "public")

    def test_rejects_unsafe_repository_name(self):
        with self.assertRaises(ValueError):
            create_private_repository(Path("vault"), "bad/name")


class ToolProbeTests(TestCase):
    @patch("codex_sync_desktop.core.onboarding.github_auth_status")
    @patch("codex_sync_desktop.core.onboarding.run")
    def test_broken_command_link_is_reported_as_unavailable(self, mocked_run, mocked_auth):
        mocked_run.side_effect = [
            CommandResult(True, "git version 2.50", 0),
            CommandResult(False, "The system cannot execute the specified program", 1),
        ]

        status = github_setup_status()

        self.assertTrue(status["git"])
        self.assertFalse(status["gh"])
        self.assertFalse(status["authenticated"])
        self.assertIn("cannot execute", status["gh_reason"])
        mocked_auth.assert_not_called()


class OfficialInstallerSelectionTests(TestCase):
    def test_selects_only_official_macos_universal_package(self):
        release = {
            "assets": [
                {"name": "gh_2.96.0_macOS_arm64.zip", "browser_download_url": "https://github.com/cli/cli/releases/download/v2.96.0/arm.zip"},
                {"name": "gh_2.96.0_macOS_universal.pkg", "browser_download_url": "https://github.com/cli/cli/releases/download/v2.96.0/gh.pkg"},
            ]
        }

        asset = select_macos_gh_installer_asset(release)

        self.assertEqual(asset["name"], "gh_2.96.0_macOS_universal.pkg")

    def test_rejects_non_github_download_host(self):
        release = {
            "assets": [
                {"name": "gh_2.96.0_macOS_universal.pkg", "browser_download_url": "https://example.com/gh.pkg"},
            ]
        }

        with self.assertRaisesRegex(RuntimeError, "不是 GitHub 官方地址"):
            select_macos_gh_installer_asset(release)
