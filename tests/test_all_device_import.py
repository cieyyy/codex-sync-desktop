import json
import tempfile
from pathlib import Path
from unittest import TestCase

from codex_sync_desktop.core.backups import create_import_transaction, finish_import_transaction, rollback_import_transaction
from codex_sync_desktop.core.import_preview import preview_versions
from codex_sync_desktop.core.sessions import apply_import, export_sanitized_sessions, plan_all_import, repository_session_summary
from tests.helpers import create_state_database, write_session


class AllDeviceImportTests(TestCase):
    identity = '019f9999-1111-7222-8333-444455556666'

    def prepare(self, root):
        vault = root / 'vault'
        for name, timestamp in [('A', '20'), ('B', '30')]:
            source = root / name
            path = write_session(source, self.identity, '共同请求', '共同答复')
            self.append(path, f'设备 {name} 新消息', timestamp)
            export_sanitized_sessions(source, vault, name)
        # An older exporter stored only the ID suffix. The JSONL identity is authoritative.
        manifest_path = vault / 'sessions-text/devices/b/manifest.json'
        data = json.loads(manifest_path.read_text())
        data['sessions'][0]['task_id'] = self.identity[-12:]
        manifest_path.write_text(json.dumps(data))
        return vault

    def append(self, path, text, seconds):
        with path.open('a') as handle:
            handle.write(json.dumps({'timestamp': f'2026-07-25T10:00:{seconds}Z', 'type': 'event_msg',
                                     'payload': {'type': 'user_message', 'message': text}}) + '\n')

    def test_combines_sources_once_and_copy_can_be_undone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = self.prepare(root)
            home = root / 'target'
            create_state_database(home)
            plan = plan_all_import(home, vault)
            self.assertEqual(len(plan.items), 1)
            self.assertEqual(plan.counts, {'copy': 1})
            item = plan.items[0]
            self.assertEqual(item.task_id, self.identity)
            self.assertFalse(item.destination.exists())
            preview = dict(preview_versions(item))['仓库会话']
            self.assertIn('设备 A 新消息', preview)
            self.assertIn('设备 B 新消息', preview)
            transaction = create_import_transaction(home, plan)
            result = apply_import(plan)
            finish_import_transaction(transaction, result['counts'])
            text = item.destination.read_text()
            self.assertIn('设备 A 新消息', text)
            self.assertIn('设备 B 新消息', text)
            self.assertEqual(text.count('共同请求'), 1)
            # Repeating the same import is idempotent.
            self.assertEqual(plan_all_import(home, vault).counts, {'skipped-existing': 1})
            rollback_import_transaction(home, transaction)
            self.assertFalse(item.destination.exists())
            self.assertFalse((home / "sync-project-membership.json").exists())

    def test_preserves_local_content_and_ignores_title_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = self.prepare(root)
            home = root / 'target'
            create_state_database(home)
            path = write_session(home, self.identity, '共同请求', '共同答复')
            self.append(path, '本机新增消息', '40')
            original = path.read_bytes()
            plan = plan_all_import(home, vault)
            self.assertEqual(plan.counts, {'skipped-existing': 1})
            self.assertEqual(plan.title_updates, {})
            from codex_sync_desktop.core.import_preview import apply_title_overrides
            self.assertEqual(apply_title_overrides(plan, {self.identity: '仓库覆盖标题'}), 0)
            result = apply_import(plan)
            self.assertEqual(result['copied'], [])
            self.assertEqual(path.read_bytes(), original)

    def test_corrupt_copy_blocks_import_even_when_another_copy_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = self.prepare(root)
            corrupt = next((vault / 'sessions-text/devices/b').rglob('*.jsonl'))
            corrupt.write_text(corrupt.read_text() + '{}\n')
            home = root / 'target'
            plan = plan_all_import(home, vault)
            self.assertEqual(plan.counts['invalid-source-hash'], 1)
            with self.assertRaises(ValueError):
                apply_import(plan)
            self.assertFalse(home.exists())

    def test_reviewed_catalog_title_wins_and_summary_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = self.prepare(root)
            (vault / 'sessions-text/title-catalog.json').write_text(json.dumps({'items': [
                {'task_id': self.identity, 'title': '审核后的统一标题'}]}))
            plan = plan_all_import(root / 'target', vault)
            self.assertEqual(plan.title_updates, {self.identity: '审核后的统一标题'})
            self.assertEqual(repository_session_summary(vault)[0], 1)

    def test_empty_repository_has_no_import_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(plan_all_import(root / 'target', root / 'vault').items, [])

    def test_database_index_and_catalog_only_ids_are_protected(self):
        import sqlite3
        from codex_sync_desktop.core.index_repair import repair_indexes
        for store in ('database', 'index', 'catalog', 'compressed'):
            with self.subTest(store=store), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                vault = self.prepare(root)
                home = root / 'target'
                create_state_database(home)
                if store == 'database':
                    path = write_session(home, self.identity)
                    repair_indexes(home, create_backup=False)
                    path.unlink()
                elif store == 'index':
                    (home / 'session_index.jsonl').write_text(json.dumps({'id': self.identity}))
                elif store == 'catalog':
                    (home / 'sqlite').mkdir()
                    with sqlite3.connect(home / 'sqlite/catalog.db') as connection:
                        connection.execute('CREATE TABLE local_thread_catalog (thread_id TEXT)')
                        connection.execute('INSERT INTO local_thread_catalog VALUES (?)', (self.identity,))
                else:
                    import zstandard
                    path = write_session(home, self.identity)
                    archive = home / 'archived_sessions/old.jsonl.zst'
                    archive.parent.mkdir()
                    archive.write_bytes(zstandard.ZstdCompressor().compress(path.read_bytes()))
                    path.unlink()
                self.assertEqual(plan_all_import(home, vault).counts, {'skipped-existing': 1})

    def test_register_new_only_preserves_local_rows_index_global_state_and_undo(self):
        import sqlite3
        from codex_sync_desktop.core.index_repair import repair_indexes, register_new_sessions
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = self.prepare(root)
            home = root / 'target'
            database = create_state_database(home)
            old = write_session(home, 'local-original', '本机标题', cwd='/my/project')
            repair_indexes(home, create_backup=False)
            with sqlite3.connect(database) as connection:
                connection.execute('ALTER TABLE threads ADD COLUMN project_id TEXT')
                connection.execute("UPDATE threads SET project_id='project-original', title='手动标题', model_provider='custom'")
                original_row = connection.execute("SELECT * FROM threads WHERE id='local-original'").fetchone()
            index = home / 'session_index.jsonl'
            index.write_bytes(index.read_bytes() + b'{"id":"index-only","extra":{"project":"untouched"}}')
            original_index = index.read_bytes()
            global_state = home / '.codex-global-state.json'
            global_state.write_bytes(b'{"projects":["/my/project"],"pinned":["local-original"]}')
            original_state = global_state.read_bytes()
            original_body = old.read_bytes()
            catalog = home / 'sqlite/codex-dev.db'
            catalog.parent.mkdir()
            with sqlite3.connect(catalog) as connection:
                connection.executescript("                    CREATE TABLE local_thread_catalog_hosts (host_id TEXT PRIMARY KEY, host_kind TEXT NOT NULL);\n                    CREATE TABLE local_thread_catalog_metadata (id INTEGER PRIMARY KEY, catalog_revision INTEGER NOT NULL DEFAULT 0);\n                    INSERT INTO local_thread_catalog_metadata VALUES (1, 4);\n                    CREATE TABLE local_thread_catalog_sync_state (\n                        host_id TEXT PRIMARY KEY, watermark_updated_at REAL,\n                        initial_build_complete INTEGER NOT NULL DEFAULT 0,\n                        observation_sequence INTEGER NOT NULL DEFAULT 0,\n                        last_full_reconciled_at INTEGER\n                    );\n                    INSERT INTO local_thread_catalog_sync_state VALUES ('local', NULL, 1, 27, NULL);\n                    CREATE TABLE local_thread_catalog (\n                        host_id TEXT NOT NULL, thread_id TEXT NOT NULL, display_title TEXT NOT NULL,\n                        source_created_at REAL NOT NULL, source_updated_at REAL NOT NULL,\n                        cwd TEXT NOT NULL, source_kind TEXT NOT NULL, source_detail TEXT,\n                        model_provider TEXT NOT NULL, git_branch TEXT, observation_sequence INTEGER NOT NULL,\n                        missing_candidate INTEGER NOT NULL DEFAULT 0, thread_source TEXT,\n                        PRIMARY KEY (host_id, thread_id)\n                    );\n")
                connection.execute("INSERT INTO local_thread_catalog VALUES ('local', 'local-original', '原项目标题', 1, 2, '/my/project', 'app', 'original-path', 'custom', 'main', 27, 0, 'user')")
                catalog_before = connection.execute("SELECT * FROM local_thread_catalog WHERE thread_id='local-original'").fetchone()
            plan = plan_all_import(home, vault)
            transaction = create_import_transaction(home, plan)
            result = apply_import(plan)
            report = register_new_sessions(home, result['copied'], plan.title_updates)
            finish_import_transaction(transaction, result['counts'])
            self.assertEqual(report.inserted, 1)
            self.assertEqual(report.catalog_inserted, 1)
            with sqlite3.connect(catalog) as connection:
                self.assertEqual(connection.execute("SELECT * FROM local_thread_catalog WHERE thread_id='local-original'").fetchone(), catalog_before)

            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT * FROM threads WHERE id='local-original'").fetchone(), original_row)
                self.assertEqual(connection.execute('SELECT count(*) FROM threads').fetchone()[0], 2)
            self.assertTrue(index.read_bytes().startswith(original_index + b'\n'))
            self.assertEqual(global_state.read_bytes(), original_state)
            self.assertEqual(old.read_bytes(), original_body)
            self.assertEqual(plan_all_import(home, vault).counts, {'skipped-existing': 1})
            rollback_import_transaction(home, transaction)
            self.assertEqual(index.read_bytes(), original_index)
            self.assertFalse(plan.items[0].destination.exists())

    def test_stale_plan_cannot_overwrite_new_local_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = self.prepare(root)
            home = root / 'target'
            plan = plan_all_import(home, vault)
            original = write_session(home, self.identity)
            before = original.read_bytes()
            with self.assertRaises(FileExistsError):
                apply_import(plan)
            self.assertEqual(original.read_bytes(), before)
            self.assertFalse(plan.items[0].destination.exists())
