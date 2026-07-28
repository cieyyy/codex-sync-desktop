from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from codex_sync_desktop.core.git_client import CommandResult
from codex_sync_desktop.core.onboarding import (
    clear_tool_installer_cache,
    create_private_repository,
    detect_system_proxy,
    github_setup_status,
    launch_dependency_install,
    select_macos_gh_installer_asset,
    select_windows_gh_installer_asset,
    select_windows_git_installer_asset,
    validate_proxy_url,
    write_windows_tool_install_script,
    _macos_proxy_candidates,
    _url_handlers,
)


class ProxyValidationTests(TestCase):
    def test_accepts_local_http_proxy(self):
        self.assertEqual(validate_proxy_url(" http://127.0.0.1:7890 "), "http://127.0.0.1:7890")

    def test_rejects_proxy_credentials_and_invalid_scheme(self):
        with self.assertRaises(ValueError):
            validate_proxy_url("http://name:secret@127.0.0.1:7890")
        with self.assertRaises(ValueError):
            validate_proxy_url("socks5://127.0.0.1:7890")

    @patch("codex_sync_desktop.core.onboarding._local_proxy_port_open", return_value=False)
    @patch("codex_sync_desktop.core.onboarding.urllib.request.getproxies", return_value={})
    @patch("codex_sync_desktop.core.onboarding._windows_proxy_candidates", return_value=["http=127.0.0.1:7890;https=127.0.0.1:7897"])
    @patch("codex_sync_desktop.core.onboarding.sys.platform", "win32")
    def test_windows_system_proxy_mapping_prefers_https(self, _windows, _proxies, _ports):
        self.assertEqual(detect_system_proxy(), "http://127.0.0.1:7897")

    @patch("codex_sync_desktop.core.onboarding.subprocess.run")
    def test_macos_reads_enabled_scutil_https_proxy(self, mocked_run):
        mocked_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": "HTTPSProxy : 127.0.0.1\nHTTPSPort : 7897\nHTTPSEnable : 1\n",
        })()

        self.assertEqual(_macos_proxy_candidates(), ["http://127.0.0.1:7897"])

    @patch("codex_sync_desktop.core.onboarding.ssl.create_default_context")
    @patch("codex_sync_desktop.core.onboarding._trusted_ca_file", return_value="trusted-ca.pem")
    def test_https_handler_uses_bundled_ca_file(self, _where, mocked_context):
        mocked_context.return_value = object()

        handlers = _url_handlers("http://127.0.0.1:7897")

        mocked_context.assert_called_once_with(cafile="trusted-ca.pem")
        self.assertEqual(len(handlers), 2)


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

    @patch("codex_sync_desktop.core.onboarding.github_auth_status")
    @patch("codex_sync_desktop.core.onboarding.run")
    def test_missing_windows_command_has_actionable_detection_reason(self, mocked_run, mocked_auth):
        mocked_run.side_effect = [
            CommandResult(False, "[WinError 2] 系统找不到指定的文件。", 1),
            CommandResult(True, "gh version 2.96", 0),
        ]
        mocked_auth.return_value = CommandResult(False, "not logged in", 1)

        status = github_setup_status()

        self.assertIn("PATH", status["git_reason"])
        self.assertIn("Windows 注册表", status["git_reason"])


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

    def test_selects_official_windows_installers(self):
        gh_release = {"assets": [{"name": "gh_2.96.0_windows_amd64.msi", "browser_download_url": "https://github.com/cli/cli/releases/download/v2.96.0/gh.msi"}]}
        git_release = {"assets": [{"name": "Git-2.51.0-64-bit.exe", "browser_download_url": "https://github.com/git-for-windows/git/releases/download/v2.51.0.windows.1/Git.exe"}]}

        self.assertTrue(str(select_windows_gh_installer_asset(gh_release)["name"]).endswith("amd64.msi"))
        self.assertTrue(str(select_windows_git_installer_asset(git_release)["name"]).endswith("64-bit.exe"))

    def test_rejects_unofficial_windows_installer_url(self):
        release = {"assets": [{"name": "Git-2.51.0-64-bit.exe", "browser_download_url": "https://example.com/Git.exe"}]}

        with self.assertRaisesRegex(RuntimeError, "不是 GitHub 官方地址"):
            select_windows_git_installer_asset(release)


class DependencyInstallFallbackTests(TestCase):
    @patch("codex_sync_desktop.core.onboarding.subprocess.Popen")
    @patch("codex_sync_desktop.core.onboarding.download_latest_macos_gh_installer", return_value=Path("GitHub-CLI.pkg"))
    @patch("codex_sync_desktop.core.onboarding.run")
    @patch("codex_sync_desktop.core.onboarding.sys.platform", "darwin")
    def test_macos_uses_system_git_installer_and_verified_gh_package(self, mocked_run, mocked_download, mocked_popen):
        mocked_run.side_effect = [CommandResult(False, "missing git", 1), CommandResult(False, "missing gh", 1)]

        with tempfile.TemporaryDirectory() as directory:
            result = launch_dependency_install(Path(directory))

        self.assertFalse(result.completed)
        mocked_download.assert_called_once()
        mocked_popen.assert_any_call(["/usr/bin/xcode-select", "--install"])
        mocked_popen.assert_any_call(["/usr/bin/open", "GitHub-CLI.pkg"])

    @patch("codex_sync_desktop.core.onboarding.clear_tool_installer_cache")
    @patch("codex_sync_desktop.core.onboarding.github_setup_status")
    @patch("codex_sync_desktop.core.onboarding.shutil.which", return_value=r"C:\Program Files\WindowsApps\winget.exe")
    @patch("codex_sync_desktop.core.onboarding.run")
    @patch("codex_sync_desktop.core.onboarding.sys.platform", "win32")
    def test_windows_winget_install_is_rechecked_automatically(self, mocked_run, _which, mocked_status, mocked_clear):
        mocked_run.side_effect = [
            CommandResult(False, "missing git", 1),
            CommandResult(False, "missing gh", 1),
            CommandResult(True, "installed git", 0),
            CommandResult(True, "installed gh", 0),
        ]
        mocked_status.return_value = {"git": True, "gh": True, "authenticated": False}

        with tempfile.TemporaryDirectory() as directory:
            result = launch_dependency_install(Path(directory))

        self.assertTrue(result.completed)
        self.assertEqual(mocked_run.call_count, 4)
        mocked_status.assert_called_once()
        mocked_clear.assert_called_once()

    @patch("codex_sync_desktop.core.onboarding.subprocess.Popen")
    @patch("codex_sync_desktop.core.onboarding.write_windows_tool_install_script")
    @patch("codex_sync_desktop.core.onboarding.download_latest_windows_tool_installers")
    @patch("codex_sync_desktop.core.onboarding.shutil.which", return_value=None)
    @patch("codex_sync_desktop.core.onboarding.run")
    @patch("codex_sync_desktop.core.onboarding.sys.platform", "win32")
    def test_windows_without_winget_downloads_official_installers(self, mocked_run, _which, mocked_download, mocked_script, mocked_popen):
        mocked_run.side_effect = [CommandResult(False, "missing git", 1), CommandResult(False, "missing gh", 1)]
        mocked_download.return_value = (Path("git.exe"), Path("gh.msi"))
        mocked_script.return_value = Path("install.ps1")

        with tempfile.TemporaryDirectory() as directory:
            result = launch_dependency_install(Path(directory))

        self.assertFalse(result.completed)
        mocked_download.assert_called_once()
        mocked_popen.assert_called_once()

    @patch("codex_sync_desktop.core.onboarding.subprocess.Popen")
    @patch("codex_sync_desktop.core.onboarding.write_windows_tool_install_script")
    @patch("codex_sync_desktop.core.onboarding.download_latest_windows_tool_installers")
    @patch("codex_sync_desktop.core.onboarding.shutil.which", return_value=None)
    @patch("codex_sync_desktop.core.onboarding.run")
    @patch("codex_sync_desktop.core.onboarding.sys.platform", "win32")
    def test_windows_fallback_only_installs_the_missing_tool(self, mocked_run, _which, mocked_download, mocked_script, mocked_popen):
        mocked_run.side_effect = [CommandResult(False, "missing git", 1), CommandResult(True, "gh version 2.96", 0)]
        mocked_download.return_value = (Path("git.exe"), None)
        mocked_script.return_value = Path("install.ps1")

        with tempfile.TemporaryDirectory() as directory:
            result = launch_dependency_install(Path(directory))

        self.assertFalse(result.completed)
        mocked_download.assert_called_once_with(
            Path(directory),
            "",
            include_git=True,
            include_gh=False,
        )
        mocked_script.assert_called_once_with(Path(directory), Path("git.exe"), None, "")
        mocked_popen.assert_called_once()

    def test_tool_installer_cache_only_removes_known_files(self):
        with tempfile.TemporaryDirectory() as directory:
            app_home = Path(directory)
            downloads = app_home / "downloads"
            downloads.mkdir()
            (downloads / "Git-for-Windows-64-bit.exe").write_bytes(b"installer")
            (downloads / "customer-file.txt").write_text("keep", encoding="utf-8")

            removed = clear_tool_installer_cache(app_home)

            self.assertEqual(removed, 1)
            self.assertTrue((downloads / "customer-file.txt").exists())

    def test_windows_install_script_waits_checks_exit_codes_and_only_removes_known_installers(self):
        with tempfile.TemporaryDirectory() as directory:
            app_home = Path(directory)
            git_installer = app_home / "downloads" / "Git-for-Windows-64-bit.exe"
            gh_installer = app_home / "downloads" / "GitHub-CLI-windows-amd64.msi"

            script = write_windows_tool_install_script(app_home, git_installer, gh_installer)
            content = script.read_text(encoding="utf-8-sig")

        self.assertIn("-Wait -PassThru", content)
        self.assertIn("$git.ExitCode", content)
        self.assertIn("$gh.ExitCode", content)
        self.assertIn(str(git_installer), content)
        self.assertIn(str(gh_installer), content)
        self.assertNotIn("Remove-Item -Recurse", content)

    def test_windows_install_script_skips_already_available_github_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            app_home = Path(directory)
            git_installer = app_home / "downloads" / "Git-for-Windows-64-bit.exe"

            script = write_windows_tool_install_script(app_home, git_installer, None)
            content = script.read_text(encoding="utf-8-sig")

        self.assertIn(str(git_installer), content)
        self.assertNotIn("msiexec.exe", content)
        self.assertNotIn("$gh.ExitCode", content)
