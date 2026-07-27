import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from codex_sync_desktop.core.backups import (
    clear_backup_storage,
    create_import_transaction,
    finish_import_transaction,
    prune_backup_history,
    rollback_import_transaction,
)
from codex_sync_desktop.core.sessions import apply_import, export_sanitized_sessions, plan_import
from tests.helpers import create_state_database, write_session


class SessionSyncTests(unittest.TestCase):
    def test_missing_active_sessions_directory_does_not_clear_existing_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            vault = root / "vault"
            exported = vault / "sessions-text" / "devices" / "office-mac" / "sessions" / "sessions" / "old.jsonl"
            exported.parent.mkdir(parents=True)
            exported.write_text("preserve", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                export_sanitized_sessions(source_home, vault, "Office Mac")

            self.assertEqual(exported.read_text(encoding="utf-8"), "preserve")

    def test_export_excludes_archived_session_and_removes_old_device_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            vault = root / "vault"
            session = write_session(source_home, "019f9999-1111-7222-8333-444455556666")
            first = export_sanitized_sessions(source_home, vault, "Office Mac")
            self.assertEqual(first.sessions, 1)
            exported_root = vault / "sessions-text" / "devices" / "office-mac" / "sessions"
            self.assertEqual(len(list(exported_root.rglob("*.jsonl"))), 1)

            archived = source_home / "archived_sessions" / session.relative_to(source_home / "sessions")
            archived.parent.mkdir(parents=True)
            session.replace(archived)
            second = export_sanitized_sessions(source_home, vault, "Office Mac")

            self.assertEqual(second.sessions, 0)
            self.assertEqual(second.removed_files, 1)
            self.assertEqual(list(exported_root.rglob("*.jsonl")), [])
            manifest = json.loads((exported_root.parent / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["sessions"], [])

    def test_exported_title_is_planned_as_source_preferred_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            write_session(source_home, session_id)
            source_database = create_state_database(source_home)
            with closing(sqlite3.connect(source_database)) as connection:
                connection.execute("INSERT INTO threads (id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode) VALUES (?,?,?,?,?,?,?,?,?,?)", (session_id, "source", 1, 1, "app", "openai", "/source", "Renamed on Mac", "{}", "never"))
                connection.commit()
            target_database = create_state_database(target_home)
            with closing(sqlite3.connect(target_database)) as connection:
                connection.execute("INSERT INTO threads (id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode) VALUES (?,?,?,?,?,?,?,?,?,?)", (session_id, "target", 1, 1, "app", "openai", "/target", "Old Windows name", "{}", "never"))
                connection.commit()

            export_sanitized_sessions(source_home, vault, "Office Mac")
            manifest = json.loads((vault / "sessions-text" / "devices" / "office-mac" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["format"], 4)
            self.assertEqual(manifest["sessions"][0]["title"], "Renamed on Mac")
            plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(plan.title_updates, {session_id: "Renamed on Mac"})

    def test_raw_destination_is_identical_to_its_sanitized_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            source = write_session(source_home, session_id, "Keep this text", "Answer")
            export_sanitized_sessions(source_home, vault, "Office Mac")
            destination = target_home / source.relative_to(source_home)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(plan.counts, {"identical": 1})

    def test_local_conversation_superset_is_not_a_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            source = write_session(source_home, session_id, "First question", "First answer")
            export_sanitized_sessions(source_home, vault, "Office Mac")
            destination = target_home / source.relative_to(source_home)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            with destination.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"timestamp": "2026-07-25T10:01:00Z", "type": "event_msg", "payload": {"type": "user_message", "message": "Follow-up"}}) + "\n")
            plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(plan.counts, {"identical": 1})

    def test_export_and_import_with_conflict_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            source = write_session(source_home, session_id, "password=super-secret-value")
            report = export_sanitized_sessions(source_home, vault, "Office Mac")
            self.assertEqual(report.sessions, 1)
            self.assertEqual(report.secrets_redacted, 0)
            plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(plan.counts, {"copy": 1})
            result = apply_import(plan)
            self.assertEqual(len(result["copied"]), 1)
            imported = result["copied"][0]
            self.assertIn("password=super-secret-value", imported.read_text(encoding="utf-8"))
            self.assertIn("function_call", imported.read_text(encoding="utf-8"))

            source.write_text(source.read_text(encoding="utf-8") + json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "new"}}) + "\n", encoding="utf-8")
            export_sanitized_sessions(source_home, vault, "Office Mac")
            conflict_plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(conflict_plan.counts, {"conflict": 1})
            before_merge = imported.read_bytes()
            transaction = create_import_transaction(target_home, conflict_plan)
            conflict_result = apply_import(conflict_plan)
            finish_import_transaction(transaction, conflict_result["counts"])
            self.assertEqual(len(conflict_result["conflicts"]), 0)
            self.assertEqual(len(conflict_result["merged"]), 1)
            self.assertFalse((target_home / "import-conflicts").exists())
            merged_text = conflict_result["merged"][0].read_text(encoding="utf-8")
            self.assertIn("super-secret-value", merged_text)
            self.assertIn('"message":"new"', merged_text)
            rollback = rollback_import_transaction(target_home, transaction)
            self.assertEqual(rollback["restored_sessions"], 1)
            self.assertEqual(imported.read_bytes(), before_merge)

    def test_transaction_rolls_back_copied_session_and_rejects_later_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            write_session(source_home, session_id, "Imported question", "Imported answer")
            export_sanitized_sessions(source_home, vault, "Office Mac")
            plan = plan_import(target_home, vault, "office-mac")
            transaction = create_import_transaction(target_home, plan)
            result = apply_import(plan)
            finish_import_transaction(transaction, result["counts"])
            imported = result["copied"][0]
            with imported.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"timestamp": "2026-07-27T12:00:00Z", "type": "event_msg", "payload": {"type": "user_message", "message": "new local work"}}) + "\n")
            with self.assertRaisesRegex(RuntimeError, "changed after import"):
                rollback_import_transaction(target_home, transaction)
            self.assertTrue(imported.exists())

    def test_transaction_removes_unchanged_copied_session_on_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            write_session(source_home, "019f9999-1111-7222-8333-444455556666", "Imported question", "Imported answer")
            export_sanitized_sessions(source_home, vault, "Office Mac")
            plan = plan_import(target_home, vault, "office-mac")
            transaction = create_import_transaction(target_home, plan)
            result = apply_import(plan)
            finish_import_transaction(transaction, result["counts"])
            imported = result["copied"][0]
            rollback = rollback_import_transaction(target_home, transaction)
            self.assertEqual(rollback["removed"], 1)
            self.assertFalse(imported.exists())

    def test_transaction_restores_database_and_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            target_home.mkdir()
            database = target_home / "state_test.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE marker (value TEXT)")
                connection.execute("INSERT INTO marker VALUES ('before')")
                connection.commit()
            index = target_home / "session_index.jsonl"
            index.write_text("before-index\n", encoding="utf-8")
            write_session(source_home, "019f9999-1111-7222-8333-444455556666")
            export_sanitized_sessions(source_home, vault, "Office Mac")
            plan = plan_import(target_home, vault, "office-mac")
            transaction = create_import_transaction(target_home, plan)
            result = apply_import(plan)
            finish_import_transaction(transaction, result["counts"])
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("UPDATE marker SET value = 'after'")
                connection.commit()
            index.write_text("after-index\n", encoding="utf-8")
            rollback = rollback_import_transaction(target_home, transaction)
            with closing(sqlite3.connect(database)) as connection:
                value = connection.execute("SELECT value FROM marker").fetchone()[0]
            self.assertEqual(value, "before")
            self.assertEqual(index.read_text(encoding="utf-8"), "before-index\n")
            self.assertEqual(rollback["restored_state"], 2)

    def test_prune_keeps_only_latest_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"
            root = codex_home / "sync-backups"
            for name in ("20260101", "20260102", "20260103"):
                path = root / name
                path.mkdir(parents=True)
                (path / "backup.json").write_text("{}", encoding="utf-8")
            self.assertEqual(prune_backup_history(codex_home, keep=1), 2)
            self.assertEqual([item.name for item in root.iterdir()], ["20260103"])

    def test_one_click_cleanup_removes_all_backup_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"
            for name in ("sync-backups", "import-backups", "import-conflicts"):
                path = codex_home / name / "batch"
                path.mkdir(parents=True)
                (path / "data.bin").write_bytes(b"1234")
            report = clear_backup_storage(codex_home)
            self.assertEqual(report["roots"], 3)
            self.assertEqual(report["files"], 3)
            self.assertEqual(report["bytes"], 12)
            for name in ("sync-backups", "import-backups", "import-conflicts"):
                self.assertFalse((codex_home / name).exists())

    def test_rejects_modified_manifest_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_session(root / "source", "019f9999-1111-7222-8333-444455556666")
            export_sanitized_sessions(root / "source", root / "vault", "Mac")
            exported = next((root / "vault" / "sessions-text" / "devices" / "mac" / "sessions").rglob("*.jsonl"))
            exported.write_text("tampered\n", encoding="utf-8")
            plan = plan_import(root / "target", root / "vault", "mac")
            self.assertEqual(plan.counts, {"invalid-source-hash": 1})
            with self.assertRaises(ValueError):
                apply_import(plan)


if __name__ == "__main__":
    unittest.main()
