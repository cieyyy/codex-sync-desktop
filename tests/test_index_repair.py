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


if __name__ == "__main__":
    unittest.main()
