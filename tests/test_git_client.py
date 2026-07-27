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
    is_transient_push_failure,
    run,
    summarize_pull,
)


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


class GitPushRecoveryTests(unittest.TestCase):
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
