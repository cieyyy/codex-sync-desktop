from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codex_sync_desktop.core.git_client import (
    CommandResult,
    VaultGit,
    command_environment,
    compact_failure_reason,
    hidden_window_kwargs,
    github_https_remote,
    is_repository_access_failure,
    is_transient_push_failure,
    run,
    summarize_pull,
    windows_registry_command_paths,
)


class GitClientEnvironmentTests(unittest.TestCase):
    def test_hidden_window_options_only_apply_to_windows(self):
        self.assertEqual(hidden_window_kwargs("darwin"), {})
        self.assertIn("creationflags", hidden_window_kwargs("win32"))

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

    def test_windows_environment_adds_standard_git_and_gh_paths(self):
        env = command_environment(
            {"PATH": r"C:\Windows\System32", "ProgramFiles": r"C:\Program Files", "LOCALAPPDATA": r"C:\Users\Buyer\AppData\Local"},
            platform_name="win32",
        )
        entries = env["PATH"].split(";")
        self.assertIn(r"C:\Users\Buyer\AppData\Local\codex-sync-desktop\tools\bin", entries)
        self.assertIn(r"C:\Program Files\Git\cmd", entries)
        self.assertIn(r"C:\Program Files\GitHub CLI", entries)
        self.assertIn(r"C:\Users\Buyer\AppData\Local\Microsoft\WinGet\Links", entries)

    @patch("codex_sync_desktop.core.git_client.sys.platform", "win32")
    def test_windows_registry_detects_custom_git_install_directory(self):
        values = {
            (2, r"SOFTWARE\GitForWindows", "InstallPath"): r"D:\Git",
        }

        class FakeKey:
            def __init__(self, root, path):
                self.root = root
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def open_key(root, path, _reserved, _access):
            return FakeKey(root, path)

        def query_value(key, name):
            lookup = (key.root, key.path, name)
            if lookup not in values:
                raise FileNotFoundError(lookup)
            return values[lookup], 1

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER=1,
            HKEY_LOCAL_MACHINE=2,
            KEY_READ=1,
            KEY_WOW64_64KEY=256,
            KEY_WOW64_32KEY=512,
            OpenKey=open_key,
            QueryValueEx=query_value,
        )
        with patch.dict("sys.modules", {"winreg": fake_winreg}):
            paths = windows_registry_command_paths()

        self.assertIn(r"D:\Git\cmd", paths)
        self.assertIn(r"D:\Git\bin", paths)

    def test_proxy_is_applied_to_git_and_github_cli_environment(self):
        env = command_environment({"PATH": "/usr/bin"}, platform_name="linux", proxy_url="http://127.0.0.1:7890")

        self.assertEqual(env["HTTP_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:7890")

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

    @patch("codex_sync_desktop.core.git_client.subprocess.run")
    def test_run_accepts_missing_output_streams_in_windowed_app(self, mocked_run):
        mocked_run.return_value = SimpleNamespace(stdout=None, stderr=None, returncode=1)

        result = run(["gh", "auth", "status"])

        self.assertFalse(result.ok)
        self.assertEqual(result.output, "")
        self.assertEqual(result.returncode, 1)

    @patch("codex_sync_desktop.core.git_client.subprocess.run")
    @patch("codex_sync_desktop.core.git_client.sys.platform", "win32")
    def test_run_hides_windows_console(self, mocked_run):
        mocked_run.return_value = SimpleNamespace(stdout="", stderr="", returncode=0)

        result = run(["git", "status"])

        self.assertTrue(result.ok)
        self.assertIn("creationflags", mocked_run.call_args.kwargs)


class GitOutputSummaryTests(unittest.TestCase):
    def test_pull_summary_uses_changed_file_count(self):
        output = """Updating abc..def
Fast-forward
 file-one | 10 +++++-----
 file-two | 2 ++
 2 files changed, 7 insertions(+), 5 deletions(-)
"""

        self.assertEqual(summarize_pull(output), "结果：成功\n数量：2 个文件\n状态：Fast-forward")

    def test_pull_summary_reports_up_to_date(self):
        self.assertEqual(
            summarize_pull("Already up to date."),
            "结果：成功\n数量：0 个文件\n状态：已经是最新",
        )

    def test_failure_reason_returns_one_relevant_line(self):
        output = "remote: checking credentials\nfatal: Authentication failed for repository\nlong trailing detail"

        self.assertEqual(compact_failure_reason(output), "GitHub 身份认证失败，请重新登录或检查仓库权限。")

    def test_transient_push_failure_has_actionable_reason(self):
        output = "error: RPC failed; curl 92 HTTP/2 stream was not closed cleanly\nfatal: the remote end hung up unexpectedly"

        self.assertTrue(is_transient_push_failure(output))
        self.assertEqual(
            compact_failure_reason(output),
            "连接在上传时中断；软件已自动使用 HTTP/1.1 重试，但仍未成功，请检查网络后重试。",
        )

    def test_repository_access_failure_has_actionable_reason(self):
        output = "Please make sure you have the correct access rights\nfatal: Could not read from remote repository."

        self.assertTrue(is_repository_access_failure(output))
        self.assertEqual(
            compact_failure_reason(output),
            "无法访问 GitHub 私有仓库；请在首次配置向导重新登录，并确认当前账号拥有该仓库权限。",
        )

    def test_converts_github_ssh_remote_to_https(self):
        self.assertEqual(
            github_https_remote("git@github.com:buyer/private-vault.git"),
            "https://github.com/buyer/private-vault.git",
        )


class GitPushRecoveryTests(unittest.TestCase):
    @patch("codex_sync_desktop.core.git_client.github_auth_status")
    @patch("codex_sync_desktop.core.git_client.run")
    def test_pull_repairs_github_credentials_and_ssh_remote_once(self, mocked_run, mocked_auth):
        mocked_auth.return_value = CommandResult(True, "logged in", 0)
        mocked_run.side_effect = [
            CommandResult(False, "fatal: Could not read from remote repository.", 128),
            CommandResult(True, "git@github.com:buyer/private-vault.git", 0),
            CommandResult(True, "credentials ready", 0),
            CommandResult(True, "", 0),
            CommandResult(True, "Already up to date.", 0),
        ]

        result = VaultGit(Path("/vault")).pull()

        self.assertTrue(result.ok)
        commands = [call.args[0] for call in mocked_run.call_args_list]
        self.assertIn(["gh", "auth", "setup-git"], commands)
        self.assertIn(
            ["git", "remote", "set-url", "origin", "https://github.com/buyer/private-vault.git"],
            commands,
        )
        self.assertEqual(commands.count(["git", "pull", "--rebase", "--autostash"]), 2)

    @patch("codex_sync_desktop.core.git_client.github_auth_status")
    @patch("codex_sync_desktop.core.git_client.run")
    def test_pull_reports_login_requirement_when_automatic_repair_cannot_authenticate(
        self,
        mocked_run,
        mocked_auth,
    ):
        mocked_auth.return_value = CommandResult(False, "not logged in", 1)
        mocked_run.side_effect = [
            CommandResult(False, "fatal: Could not read from remote repository.", 128),
            CommandResult(True, "https://github.com/buyer/private-vault.git", 0),
        ]

        result = VaultGit(Path("/vault")).pull()

        self.assertFalse(result.ok)
        self.assertIn("GitHub CLI 尚未登录", result.output)
        self.assertNotIn(["gh", "auth", "setup-git"], [call.args[0] for call in mocked_run.call_args_list])

    @patch("codex_sync_desktop.core.git_client.run")
    def test_pull_sets_upstream_and_retries_when_tracking_is_missing(self, mocked_run):
        mocked_run.side_effect = [
            CommandResult(False, "There is no tracking information for the current branch.", 1),
            CommandResult(True, "main", 0),
            CommandResult(True, "fetched", 0),
            CommandResult(True, "branch 'main' set up to track 'origin/main'", 0),
            CommandResult(True, "Already up to date.", 0),
        ]

        result = VaultGit(Path("/vault")).pull()

        self.assertTrue(result.ok)
        self.assertEqual(
            mocked_run.call_args_list[3].args[0],
            ["git", "branch", "--set-upstream-to", "origin/main", "main"],
        )
        self.assertEqual(
            mocked_run.call_args_list[-1].args[0],
            ["git", "pull", "--rebase", "--autostash"],
        )

    @patch("codex_sync_desktop.core.git_client.run")
    def test_pull_without_upstream_accepts_empty_remote(self, mocked_run):
        mocked_run.side_effect = [
            CommandResult(False, "There is no tracking information for the current branch.", 1),
            CommandResult(True, "main", 0),
            CommandResult(False, "fatal: couldn't find remote ref main", 128),
        ]

        result = VaultGit(Path("/vault")).pull()

        self.assertTrue(result.ok)
        self.assertEqual(result.output, "Remote repository is empty")

    @patch("codex_sync_desktop.core.git_client.run")
    def test_sets_upstream_for_first_commit_in_new_private_repository(self, mocked_run):
        mocked_run.side_effect = [
            CommandResult(True, "", 0),
            CommandResult(False, "", 1),
            CommandResult(True, "committed", 0),
            CommandResult(False, "fatal: The current branch main has no upstream branch.", 128),
            CommandResult(True, "branch 'main' set up to track 'origin/main'", 0),
        ]

        result = VaultGit(Path("/vault")).commit_and_push("first sync")

        self.assertTrue(result.ok)
        self.assertEqual(mocked_run.call_args_list[-1].args[0], ["git", "push", "--set-upstream", "origin", "HEAD"])

    @patch("codex_sync_desktop.core.git_client.run")
    def test_empty_new_private_repository_is_ready_to_sync(self, mocked_run):
        mocked_run.return_value = CommandResult(
            False,
            "Your configuration specifies to merge with refs/heads/main from the remote, but no such ref was fetched.",
            1,
        )

        result = VaultGit(Path("/vault")).pull()

        self.assertTrue(result.ok)
        self.assertEqual(result.output, "Remote repository is empty")

    @patch("codex_sync_desktop.core.git_client.run")
    def test_pushes_pending_commit_when_worktree_has_no_new_changes(self, mocked_run):
        mocked_run.side_effect = [
            CommandResult(True, "", 0),
            CommandResult(True, "", 0),
            CommandResult(True, "pushed pending commit", 0),
        ]

        result = VaultGit(Path("/vault")).commit_and_push("sync")

        self.assertTrue(result.ok)
        self.assertEqual(mocked_run.call_args_list[-1].args[0], ["git", "push"])
        self.assertEqual(mocked_run.call_count, 3)

    @patch("codex_sync_desktop.core.git_client.run")
    def test_retries_transient_push_with_http_1_1(self, mocked_run):
        mocked_run.side_effect = [
            CommandResult(True, "", 0),
            CommandResult(False, "", 1),
            CommandResult(True, "committed", 0),
            CommandResult(False, "fatal: the remote end hung up unexpectedly", 1),
            CommandResult(True, "pushed with fallback", 0),
        ]

        result = VaultGit(Path("/vault")).commit_and_push("sync")

        self.assertTrue(result.ok)
        self.assertEqual(
            mocked_run.call_args_list[-1].args[0],
            ["git", "-c", "http.version=HTTP/1.1", "push"],
        )


if __name__ == "__main__":
    unittest.main()
