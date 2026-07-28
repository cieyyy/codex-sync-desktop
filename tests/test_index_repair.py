import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from codex_sync_desktop.core.backups import create_consistent_backup, restore_backup
from codex_sync_desktop.core.index_repair import repair_indexes
from tests.helpers import create_state_database, write_session


class IndexRepairTests(unittest.TestCase):
    def test_backup_preserves_nested_database_path(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"
            nested = codex_home / "sqlite"
            nested.mkdir(parents=True)
            database = nested / "codex-dev.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE marker (value TEXT)")
                connection.execute("INSERT INTO marker VALUES ('before')")
                connection.commit()
            backup = create_consistent_backup(codex_home)
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("UPDATE marker SET value='after'")
                connection.commit()
            restored = restore_backup(codex_home, backup)
            self.assertIn(database, restored)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT value FROM marker").fetchone()[0], "before")

    def test_rebuilds_database_and_index_with_path_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"
            database = create_state_database(codex_home)
            session_id = "019f9999-1111-7222-8333-444455556666"
            session = write_session(codex_home, session_id, "Continue project sync", cwd=r"C:\Users\EDY\Projects\demo")
            report = repair_indexes(codex_home, {r"C:\Users\EDY\Projects": "/Users/wss/Projects"})
            self.assertEqual(report.inserted, 1)
            self.assertIsNotNone(report.backup_dir)
            with closing(sqlite3.connect(database)) as connection:
                row = connection.execute("SELECT rollout_path, cwd, title, preview FROM threads WHERE id = ?", (session_id,)).fetchone()
            self.assertEqual(row[0], str(session.resolve()))
            self.assertEqual(row[1], "/Users/wss/Projects/demo")
            self.assertEqual(row[2], "Continue project sync")
            self.assertEqual(row[3], "Continue project sync")
            index = [json.loads(line) for line in (codex_home / "session_index.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(index[0]["id"], session_id)

    def test_preserves_existing_title_and_can_restore_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"
            database = create_state_database(codex_home)
            session_id = "019f9999-1111-7222-8333-444455556666"
            write_session(codex_home, session_id, "Long original first prompt")
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("INSERT INTO threads (id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode) VALUES (?,?,?,?,?,?,?,?,?,?)", (session_id, "old", 1, 1, "app", "openai", "/old", "My saved title", "{}", "never"))
                connection.commit()
            report = repair_indexes(codex_home)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT title FROM threads WHERE id=?", (session_id,)).fetchone()[0], "My saved title")
                connection.execute("DELETE FROM threads")
                connection.commit()
            restored = restore_backup(codex_home, report.backup_dir)
            self.assertIn(database, restored)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT title FROM threads WHERE id=?", (session_id,)).fetchone()[0], "My saved title")

    def test_source_preferred_title_updates_database_name_and_index(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"
            database = create_state_database(codex_home)
            session_id = "019f9999-1111-7222-8333-444455556666"
            write_session(codex_home, session_id, "Original prompt")
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("INSERT INTO threads (id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode,name) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (session_id, "old", 1, 1, "app", "openai", "/old", "Old local title", "{}", "never", "Old local title"))
                connection.commit()

            repair_indexes(codex_home, create_backup=False, preferred_titles={session_id: "Renamed on source"})

            with closing(sqlite3.connect(database)) as connection:
                title, name = connection.execute("SELECT title, name FROM threads WHERE id=?", (session_id,)).fetchone()
            self.assertEqual((title, name), ("Renamed on source", "Renamed on source"))
            index = [json.loads(line) for line in (codex_home / "session_index.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(index[0]["thread_name"], "Renamed on source")

    def test_modern_codex_database_is_preferred_over_legacy_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"
            legacy = create_state_database(codex_home)
            modern_root = codex_home / "sqlite"
            modern_root.mkdir()
            modern = modern_root / "codex-dev.db"
            legacy.replace(modern)
            create_state_database(codex_home)
            session_id = "019f9999-1111-7222-8333-444455556666"
            write_session(codex_home, session_id)

            repair_indexes(codex_home, create_backup=False)

            with closing(sqlite3.connect(modern)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM threads WHERE id=?", (session_id,)).fetchone()[0], 1)

    def test_duplicate_session_ids_choose_richer_active_content_without_unique_error(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"
            database = create_state_database(codex_home)
            session_id = "019f9999-1111-7222-8333-444455556666"
            first = write_session(codex_home, session_id, "Original prompt", "Short answer")
            second = codex_home / "sessions" / "2026" / "07" / "26" / f"rollout-copy-{session_id}.jsonl"
            second.parent.mkdir(parents=True)
            records = [json.loads(line) for line in first.read_text(encoding="utf-8").splitlines()]
            records.append({
                "timestamp": "2026-07-26T12:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "A much richer continuation from another device"}],
                },
            })
            second.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")

            report = repair_indexes(codex_home, create_backup=False)

            self.assertEqual(report.inserted, 1)
            self.assertTrue(any("同会话 ID" in warning for warning in report.warnings))
            with closing(sqlite3.connect(database)) as connection:
                rows = connection.execute("SELECT id, rollout_path FROM threads WHERE id=?", (session_id,)).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][1], str(second.resolve()))
            index = [json.loads(line) for line in (codex_home / "session_index.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len([item for item in index if item["id"] == session_id]), 1)

    def test_injected_context_is_never_used_as_title(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"
            database = create_state_database(codex_home)
            session_id = "019f9999-1111-7222-8333-444455556666"
            session = write_session(codex_home, session_id, "Real deployment request", "Done")
            records = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
            records.insert(1, {
                "timestamp": "2026-07-25T10:00:00.100Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "# AGENTS.md instructions\n<INSTRUCTIONS>system rules</INSTRUCTIONS>"},
                        {"type": "input_text", "text": "<environment_context><cwd>D:\\project</cwd></environment_context>"},
                    ],
                },
            })
            session.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "INSERT INTO threads (id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (session_id, "old", 1, 1, "app", "openai", "/old", "AGENTS.md instructions system rules", "{}", "never"),
                )
                connection.commit()

            repair_indexes(codex_home, create_backup=False)

            with closing(sqlite3.connect(database)) as connection:
                title = connection.execute("SELECT title FROM threads WHERE id=?", (session_id,)).fetchone()[0]
            self.assertEqual(title, "Real deployment request")


if __name__ == "__main__":
    unittest.main()
