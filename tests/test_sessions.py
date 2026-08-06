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
from codex_sync_desktop.core.import_preview import (
    apply_title_overrides,
    items_for_category,
    preview_sources,
    preview_versions,
    render_session_bytes,
)
from codex_sync_desktop.core.models import ImportItem, ImportPlan
from codex_sync_desktop.core.sessions import (
    NoActiveSessionsError,
    apply_import,
    export_sanitized_sessions,
    list_source_device_options,
    plan_import,
)
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

            with self.assertRaises(NoActiveSessionsError):
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
            self.assertEqual(plan.source_label, "Office Mac")
            self.assertEqual(plan.title_updates, {session_id: "Renamed on Mac"})
            self.assertEqual(plan.items[0].task_id, session_id)
            self.assertEqual(plan.items[0].source_title, "Renamed on Mac")
            self.assertEqual(plan.items[0].local_title, "Old Windows name")

    def test_export_manifest_records_original_model_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            session = write_session(source_home, session_id)
            records = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
            records[0]["payload"]["model_provider"] = "team_proxy"
            session.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")

            export_sanitized_sessions(source_home, vault, "Office Mac")

            manifest = json.loads(
                (vault / "sessions-text" / "devices" / "office-mac" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["sessions"][0]["original_model_provider"], "team_proxy")

    def test_export_migrates_legacy_generic_slug_for_same_named_device(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            vault = root / "vault"
            write_session(source_home, "019f9999-1111-7222-8333-444455556666")
            legacy_root = vault / "sessions-text" / "devices" / "device"
            legacy_root.mkdir(parents=True)
            (legacy_root / "manifest.json").write_text(
                json.dumps({"format": 4, "device": "天文", "device_slug": "device", "sessions": []}),
                encoding="utf-8",
            )

            export_sanitized_sessions(source_home, vault, "天文")

            self.assertFalse(legacy_root.exists())
            manifest = json.loads(
                (vault / "sessions-text" / "devices" / "天文" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["device_slug"], "天文")

    def test_source_device_options_use_manifest_display_name(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            device_root = vault / "sessions-text" / "devices" / "device"
            device_root.mkdir(parents=True)
            (device_root / "manifest.json").write_text(
                json.dumps({"format": 4, "device": "天文", "device_slug": "device", "sessions": []}),
                encoding="utf-8",
            )

            self.assertEqual(list_source_device_options(vault), [("天文", "device")])

    def test_preview_title_override_survives_a_replanned_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            write_session(source_home, session_id)
            source_database = create_state_database(source_home)
            with closing(sqlite3.connect(source_database)) as connection:
                connection.execute(
                    "INSERT INTO threads (id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (session_id, "source", 1, 1, "app", "openai", "/source", "Source title", "{}", "never"),
                )
                connection.commit()
            export_sanitized_sessions(source_home, vault, "Office Mac")

            preview_plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(apply_title_overrides(preview_plan, {session_id: "My edited title"}), 1)
            self.assertEqual(preview_plan.title_updates[session_id], "My edited title")

            import_plan = plan_import(target_home, vault, "office-mac")
            apply_title_overrides(import_plan, {session_id: "My edited title"})
            self.assertEqual(import_plan.title_updates[session_id], "My edited title")
            self.assertEqual(len(items_for_category(import_plan, "title-update")), 1)

    def test_preview_failure_category_combines_both_verification_failures(self):
        plan = ImportPlan(
            source_device="source",
            items=[
                ImportItem("missing-source", "missing.jsonl", Path("missing"), Path("target")),
                ImportItem("invalid-source-hash", "invalid.jsonl", Path("invalid"), Path("target")),
                ImportItem("copy", "copy.jsonl", Path("copy"), Path("target")),
            ],
        )
        self.assertEqual(len(items_for_category(plan, "failure")), 2)
        self.assertEqual(len(items_for_category(plan, "copy")), 1)

    def test_preview_conflict_exposes_source_local_and_merged_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_session(root / "source", "019f9999-1111-7222-8333-444455556666", "Source question")
            local = write_session(root / "local", "019f9999-1111-7222-8333-444455556666", "Local question")
            merged = source.read_bytes() + local.read_bytes()
            item = ImportItem("conflict", "sessions/example.jsonl", source, local, merged_content=merged)
            versions = dict(preview_versions(item))
            self.assertEqual(list(versions), ["来源设备", "本机", "合并后"])
            self.assertIn("Source question", versions["来源设备"])
            self.assertIn("Local question", versions["本机"])
            self.assertIn("Source question", versions["合并后"])
            self.assertIn("Local question", versions["合并后"])

    def test_title_override_equal_to_local_title_removes_pending_update(self):
        task_id = "019f9999-1111-7222-8333-444455556666"
        item = ImportItem(
            "identical",
            "sessions/example.jsonl",
            Path("source"),
            Path("destination"),
            task_id=task_id,
            source_title="Incoming title",
            local_title="Keep local title",
        )
        plan = ImportPlan("source", [item], {task_id: "Incoming title"})
        apply_title_overrides(plan, {task_id: "Keep local title"})
        self.assertEqual(plan.title_updates, {})

    def test_preview_renders_conversation_and_tool_records(self):
        records = [
            {"timestamp": "2026-07-25T10:00:01Z", "type": "event_msg", "payload": {"type": "user_message", "message": "Question"}},
            {"timestamp": "2026-07-25T10:00:02Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Answer"}]}},
            {"timestamp": "2026-07-25T10:00:03Z", "type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "git status"}},
        ]
        content = "".join(json.dumps(record) + "\n" for record in records).encode("utf-8")
        preview = render_session_bytes(content)
        self.assertIn("用户", preview)
        self.assertIn("Question", preview)
        self.assertIn("助手", preview)
        self.assertIn("Answer", preview)
        self.assertIn("命令 / 工具调用：shell", preview)

    def test_preview_renders_every_record_beyond_previous_limits(self):
        records = [
            {
                "timestamp": f"2026-07-25T10:{index // 60:02d}:{index % 60:02d}Z",
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": f"record-{index:03d}-" + ("x" * 4096),
                },
            }
            for index in range(320)
        ]
        content = "".join(json.dumps(record) + "\n" for record in records).encode("utf-8")

        preview = render_session_bytes(content)

        self.assertGreater(len(content), 512 * 1024)
        self.assertIn("record-000-", preview)
        self.assertIn("record-319-", preview)
        self.assertNotIn("预览已截断", preview)

    def test_preview_source_streams_the_selected_version_to_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            records = [
                {
                    "type": "event_msg",
                    "payload": {"type": "agent_message", "message": f"answer-{index:03d}"},
                }
                for index in range(300)
            ]
            path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            item = ImportItem("copy", "sessions/session.jsonl", path, Path(directory) / "missing")

            sources = preview_sources(item)
            rendered = list(sources[0].iter_records())

            self.assertEqual(len(rendered), 300)
            self.assertIn("answer-299", rendered[-1])

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

    def test_manifest_hash_accepts_git_crlf_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_session(root / "source", "019f9999-1111-7222-8333-444455556666")
            export_sanitized_sessions(root / "source", root / "vault", "Mac")
            exported = next((root / "vault" / "sessions-text" / "devices" / "mac" / "sessions").rglob("*.jsonl"))
            exported.write_bytes(exported.read_bytes().replace(b"\n", b"\r\n"))

            plan = plan_import(root / "target", root / "vault", "mac")

            self.assertNotIn("invalid-source-hash", plan.counts)


if __name__ == "__main__":
    unittest.main()
