from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from codex_sync_desktop.app import CodexSyncApp
from codex_sync_desktop.core.git_client import CommandResult


class FirstRunWorkflowTests(TestCase):
    @patch("codex_sync_desktop.app.VaultGit")
    @patch("codex_sync_desktop.app.export_sanitized_sessions")
    def test_first_run_forces_initial_private_repository_push(self, mocked_export, mocked_git):
        mocked_export.return_value = SimpleNamespace(sessions=7, removed_files=2, media_removed=4)
        mocked_git.return_value.commit_and_push.return_value = CommandResult(True, "pushed", 0)
        fake_app = SimpleNamespace(
            settings=SimpleNamespace(
                codex_path=Path("codex-home"),
                device_name="Buyer Laptop",
                proxy_url="http://127.0.0.1:7890",
                auto_push_after_export=False,
            ),
            logger=Mock(),
            _checked_git=Mock(),
        )

        with tempfile.TemporaryDirectory() as directory:
            summary = CodexSyncApp._export_and_push_work(fake_app, Path(directory), force_push=True)

        mocked_git.return_value.commit_and_push.assert_called_once_with("sync: update buyer-laptop")
        fake_app._checked_git.assert_called_once()
        self.assertIn("活动会话：7", summary)
        self.assertIn("停止同步：2", summary)

    @patch("codex_sync_desktop.app.VaultGit")
    @patch("codex_sync_desktop.app.export_sanitized_sessions")
    def test_manual_export_respects_disabled_auto_push(self, mocked_export, mocked_git):
        mocked_export.return_value = SimpleNamespace(sessions=1, removed_files=0, media_removed=0)
        fake_app = SimpleNamespace(
            settings=SimpleNamespace(
                codex_path=Path("codex-home"),
                device_name="Laptop",
                proxy_url="",
                auto_push_after_export=False,
            ),
            logger=Mock(),
            _checked_git=Mock(),
        )

        with tempfile.TemporaryDirectory() as directory:
            CodexSyncApp._export_and_push_work(fake_app, Path(directory))

        mocked_git.return_value.commit_and_push.assert_not_called()
