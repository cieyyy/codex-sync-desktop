from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from codex_sync_desktop.app import CodexSyncApp
from codex_sync_desktop.core.git_client import CommandResult
from codex_sync_desktop.core.models import ImportItem, ImportPlan


class FirstRunWorkflowTests(TestCase):
    @patch("codex_sync_desktop.app.messagebox.askyesno", return_value=True)
    @patch("codex_sync_desktop.app.running_codex_processes", return_value=[])
    @patch("codex_sync_desktop.app.prune_backup_history")
    @patch("codex_sync_desktop.app.repair_indexes")
    @patch("codex_sync_desktop.app.plan_all_import")
    @patch("codex_sync_desktop.app.export_sanitized_sessions")
    @patch("codex_sync_desktop.app.VaultGit")
    def test_one_click_preserves_indexes_when_no_new_sessions(
        self,
        mocked_git,
        mocked_export,
        mocked_plan,
        mocked_repair,
        mocked_prune,
        _processes,
        _confirm,
    ):
        mocked_plan.return_value = ImportPlan(
            source_device="source-device",
            items=[ImportItem("identical", "sessions/example.jsonl", Path("source"), Path("destination"))],
        )
        mocked_export.return_value = SimpleNamespace(sessions=1, removed_files=0)
        mocked_git.return_value.pull.return_value = CommandResult(True, "pulled", 0)
        mocked_git.return_value.commit_and_push.return_value = CommandResult(True, "pushed", 0)
        fake_app = SimpleNamespace(
            settings=SimpleNamespace(codex_path=Path("codex-home"), device_name="local-device", proxy_url=""),
            _require_vault=lambda: Path("vault"),
            _checked_git=Mock(),
            refresh_all=Mock(),
            _report_progress=Mock(),
        )
        fake_app._run_task = lambda _label, work, _callback: work()

        CodexSyncApp.sync_once(fake_app)

        mocked_repair.assert_not_called()
        mocked_prune.assert_not_called()

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
            _report_progress=Mock(),
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
            _report_progress=Mock(),
        )

        with tempfile.TemporaryDirectory() as directory:
            CodexSyncApp._export_and_push_work(fake_app, Path(directory))

        mocked_git.return_value.commit_and_push.assert_not_called()

    @patch("codex_sync_desktop.app.export_documents")
    def test_configured_document_export_reports_errors(self, mocked_documents):
        mocked_documents.return_value = {"files": [
            {"status": "ok"},
            {"status": "error", "project": "demo", "source": "bad.xls", "error": "旧格式"},
        ]}
        fake_app = SimpleNamespace(
            settings=SimpleNamespace(document_roots={"demo": "project"}, device_name="Laptop"),
            logger=Mock(), _report_progress=Mock(),
        )
        summary = CodexSyncApp._export_project_documents(fake_app, Path("vault"))
        mocked_documents.assert_called_once_with(Path("vault"), "Laptop", {"demo": "project"})
        self.assertIn("文档成功：1；文档失败：1", summary)
        fake_app.logger.warning.assert_called_once()
