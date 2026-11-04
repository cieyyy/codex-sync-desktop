import json
import tempfile
from pathlib import Path
from unittest import TestCase

from codex_sync_desktop.core.sessions import (
    export_sanitized_sessions, plan_all_import, standalone_import_records,
)
from tests.helpers import create_state_database, write_session


class ImportHistoryCompatibilityTests(TestCase):
    identity = '019f9999-1111-7222-8333-444455556666'

    def test_paginated_import_has_canonical_name_and_standalone_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            path = write_session(source, self.identity, 'original question', 'original answer')
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[0]['payload']['history_mode'] = 'paginated'
            path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            export_sanitized_sessions(source, root / 'vault', 'A')
            target = root / 'target'
            create_state_database(target)
            item = plan_all_import(target, root / 'vault').items[0]
            self.assertEqual(item.destination.name, f'rollout-2026-07-25T10-00-00-{self.identity}.jsonl')
            imported = [json.loads(line) for line in item.merged_content.splitlines()]
            self.assertEqual(imported[0]['payload']['history_mode'], 'paginated')
            self.assertNotIn('history_base', imported[0]['payload'])
            self.assertEqual([{k: v for k, v in row.items() if k != 'ordinal'} for row in imported[1:3]], rows[1:3])
            self.assertEqual([row['ordinal'] for row in imported], list(range(len(imported))))
            from codex_sync_desktop.core.sessions import apply_import
            from codex_sync_desktop.core.index_repair import register_new_sessions
            import sqlite3
            copied = apply_import(plan_all_import(target, root / 'vault'))['copied']
            register_new_sessions(target, copied)
            with sqlite3.connect(target / 'state_5.sqlite') as connection:
                self.assertEqual(connection.execute('SELECT history_mode FROM threads').fetchone()[0], 'paginated')
            self.assertEqual(json.loads(path.read_text().splitlines()[0])['payload']['history_mode'], 'paginated')

    def test_merged_history_removes_offsets_without_changing_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = write_session(root, self.identity)
            rows = [json.loads(line) for line in original.read_text().splitlines()]
            fragment = root / 'fragment.jsonl'
            meta = {**rows[0], 'payload': {**rows[0]['payload'], 'history_mode': 'paginated',
                    'history_base': {'thread_id': self.identity, 'end_byte_offset': 123}}}
            fragment.write_text(json.dumps(meta) + '\n')
            merged = [meta, *rows[1:]]
            fixed = standalone_import_records(merged, [original, fragment])
            self.assertEqual([{k: v for k, v in row.items() if k != 'ordinal'} for row in fixed[1:]], merged[1:])
            self.assertNotIn('history_base', fixed[0]['payload'])
            self.assertIn('history_base', meta['payload'])
            with self.assertRaises(ValueError):
                standalone_import_records(merged, [fragment])
            meta['payload']['history_base']['thread_id'] = 'missing-source'
            fragment.write_text(json.dumps(meta) + '\n')
            with self.assertRaises(ValueError):
                standalone_import_records(merged, [original, fragment])
