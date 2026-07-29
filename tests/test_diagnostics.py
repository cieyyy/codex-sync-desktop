from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from codex_sync_desktop.core import diagnostics


class PlatformDescriptionTests(TestCase):
    def test_windows_uses_version_api_without_shelling_out(self) -> None:
        version = SimpleNamespace(major=10, minor=0, build=22631)
        with (
            patch.object(diagnostics.sys, "platform", "win32"),
            patch.object(diagnostics.sys, "getwindowsversion", return_value=version, create=True),
            patch.object(diagnostics.platform, "platform", side_effect=AssertionError("must not run")),
        ):
            self.assertEqual(diagnostics.platform_description(), "Windows-10.0.22631")

    def test_platform_failure_falls_back_to_sys_platform(self) -> None:
        with (
            patch.object(diagnostics.sys, "platform", "test-platform"),
            patch.object(diagnostics.platform, "platform", side_effect=AttributeError("missing output")),
        ):
            self.assertEqual(diagnostics.platform_description(), "test-platform")


class RemediationTests(TestCase):
    def test_empty_codex_home_does_not_report_missing_sidebar_index(self) -> None:
        report = {
            "sessions": 0,
            "session_index": False,
        }

        status, detail = diagnostics.session_index_summary(report)
        text = diagnostics.remediation_text({
            **report,
            "platform": "Windows-10.0.22631",
            "codex_home_exists": True,
            "databases": ["state.sqlite"],
            "git": True,
            "git_lfs": True,
            "git_lfs_required": False,
            "gh": True,
            "gh_authenticated": True,
            "vault_exists": True,
        })

        self.assertEqual(status, "待生成（正常）")
        self.assertIn("无需创建", detail)
        self.assertNotIn("侧栏索引：完成会话导入", text)

    def test_existing_sessions_still_require_missing_sidebar_index_repair(self) -> None:
        status, detail = diagnostics.session_index_summary({
            "sessions": 3,
            "session_index": False,
        })

        self.assertEqual(status, "缺失")
        self.assertIn("导入并修复", detail)

    def test_windows_commands_and_optional_tools_are_explained(self) -> None:
        text = diagnostics.remediation_text({
            "platform": "Windows-10.0.22631",
            "codex_home_exists": True,
            "databases": ["state.sqlite"],
            "session_index": True,
            "git": False,
            "git_lfs": False,
            "git_lfs_required": False,
            "gh": False,
            "gh_authenticated": False,
            "vault_exists": True,
        })

        self.assertIn("Git.Git", text)
        self.assertIn("GitHub.GitLFS", text)
        self.assertIn("GitHub.cli", text)
        self.assertIn("当前仓库未使用，可选", text)

    def test_detects_lfs_attributes(self) -> None:
        with TemporaryDirectory() as temporary:
            vault = Path(temporary)
            (vault / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")

            self.assertTrue(diagnostics.vault_uses_lfs(vault))

    def test_required_lfs_is_not_listed_as_optional(self) -> None:
        text = diagnostics.remediation_text({
            "platform": "Windows-10.0.22631",
            "codex_home_exists": True,
            "databases": ["state.sqlite"],
            "session_index": True,
            "git": True,
            "git_lfs": False,
            "git_lfs_required": True,
            "gh": True,
            "gh_authenticated": True,
            "vault_exists": True,
        })

        required_section = text.split("可选项", 1)[0]
        self.assertIn("Git LFS（当前仓库必需）", required_section)
