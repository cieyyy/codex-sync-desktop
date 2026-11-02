import json
from pathlib import Path
import tempfile
from unittest import TestCase
import zstandard

from codex_sync_desktop.core.conversation_documents import export_conversation_documents
from codex_sync_desktop.core.sessions import export_sanitized_sessions


class ConversationDocumentsTests(TestCase):
    def test_all_sessions_include_compressed_archives_and_only_referenced_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, vault, project = root / 'codex', root / 'vault', root / 'my project'
            project.mkdir()
            (project / '报告.md').write_text('正文', encoding='utf-8')
            (project / 'unrelated.md').write_text('不要收集', encoding='utf-8')
            (home / 'sessions').mkdir(parents=True)
            (home / 'archived_sessions').mkdir()
            rows = [
                {'type': 'session_meta', 'payload': {'id': 'test-task', 'cwd': str(project)}},
                {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': '[报告](报告.md)'}},
                {'type': 'response_item', 'payload': {'arguments': json.dumps({'path': str(project / '报告.md')})}},
            ]
            text = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
            (home / 'sessions' / 'active.jsonl').write_text(text, encoding='utf-8')
            (home / 'archived_sessions' / 'old.jsonl.zst').write_bytes(zstandard.ZstdCompressor().compress(text.encode()))
            report = export_sanitized_sessions(home, vault, 'Laptop', include_archived=True)
            self.assertEqual(report.sessions, 2)
            self.assertTrue((report.output / 'sessions/archived_sessions/old.jsonl').is_file())
            index = export_conversation_documents(home, vault, 'Laptop')
            self.assertEqual(index['sessions_scanned'], 2)
            self.assertEqual(len(index['files']), 1)
            self.assertEqual(index['files'][0]['source'], '报告.md')
            self.assertEqual(len(index['files'][0]['sessions']), 2)
            self.assertEqual((vault / index['files'][0]['text_path']).read_text(), '正文')
            index_path = vault.resolve() / 'documents-text/devices/laptop/index.json'
            timestamp = index_path.stat().st_mtime_ns
            second = export_conversation_documents(home, vault, 'Laptop')
            self.assertEqual(index, second)
            self.assertEqual(timestamp, index_path.stat().st_mtime_ns)

    def test_missing_reference_is_listed_without_exporting_an_unrelated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'codex'
            (home / 'sessions').mkdir(parents=True)
            (home / 'sessions' / 'a.jsonl').write_text(json.dumps({
                'type': 'session_meta', 'payload': {'cwd': str(root), 'path': str(root / 'missing.docx')}}))
            index = export_conversation_documents(home, root / 'vault', 'Laptop')
            self.assertEqual(index['files'], [])
            self.assertEqual(index['unresolved'][0]['path'], str((root / 'missing.docx').resolve()))
