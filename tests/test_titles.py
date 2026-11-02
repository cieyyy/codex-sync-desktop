from unittest import TestCase
import json
import tempfile
from pathlib import Path

from codex_sync_desktop.core.titles import infer_session_title, is_usable_title, title_candidate
from tests.helpers import write_session, create_state_database
from codex_sync_desktop.core.sessions import export_sanitized_sessions, plan_import
from codex_sync_desktop.core.index_repair import repair_indexes


class TitleQualityTests(TestCase):
    def test_rejects_injected_context_titles(self):
        self.assertFalse(is_usable_title("AGENTS.md instructions 你是我的运维助手"))
        self.assertFalse(is_usable_title("<environment_context> <cwd>D:\\project</cwd>"))

    def test_extracts_request_after_attachment_preamble(self):
        text = "# Files mentioned by the user:\n\n## My request for Codex:\n修复生产环境部署脚本"

        self.assertEqual(title_candidate(text), "修复生产环境部署脚本")

    def test_skips_context_and_continue_to_find_real_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_session(Path(directory), "request", "<environment_context>context</environment_context>")
            with path.open("a") as handle:
                for message in ("继续", "# Files mentioned by the user:\n## My request:\n修复同步软件代理开关。附上日志"):
                    handle.write(json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": message}}) + "\n")
            self.assertEqual(infer_session_title(path), "修复同步软件代理开关")

    def _imported(self, root, data):
        return write_session(root, "072c7aec-0000-5d21-b716-0ea78b59d049",
                             "Import VS Code chat session for browsing: VS Code Chat",
                             "# Imported VS Code chat data\n```json\n" + json.dumps(data) + "\n```")

    def test_recovers_original_vscode_request_from_raw_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._imported(Path(directory), [{"items": [{"v": {"requests": [
                {"message": {"text": "排查数据库连接失败。报错如下"}}
            ]}}]}])
            self.assertEqual(infer_session_title(path), "排查数据库连接失败")

    def test_uses_recovered_descriptive_title_when_messages_are_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._imported(Path(directory), {"title": "yaml文件作用解析", "request_count": 0})
            self.assertEqual(infer_session_title(path), "yaml文件作用解析")

    def test_empty_import_is_named_honestly_and_propagated_to_indexes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target, vault = root / "source", root / "target", root / "vault"
            path = self._imported(source, {"is_empty": True, "title": "VS Code Chat", "requests": []})
            before = path.read_bytes()
            export_sanitized_sessions(source, vault, "Mac")
            # Emulate an existing vault whose manifest did not include titles.
            manifest_path = vault / "sessions-text/devices/mac/manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest['sessions'][0].pop('title')
            manifest_path.write_text(json.dumps(manifest))
            plan = plan_import(target, vault, "mac")
            item = plan.items[0]
            self.assertEqual(item.source_title, "VS Code 空会话（072c7aec）")
            self.assertEqual(plan.title_updates[item.task_id], item.source_title)
            create_state_database(source)
            repair_indexes(source, create_backup=False)
            index = json.loads((source / 'session_index.jsonl').read_text())
            self.assertEqual(index['thread_name'], item.source_title)
            self.assertEqual(path.read_bytes(), before)

    def test_generic_saved_title_is_rejected(self):
        self.assertFalse(is_usable_title("Import VS Code chat session for browsing: VS Code Chat"))

    def test_long_prompt_produces_short_title(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_session(Path(directory), "long", "分析项目部署失败原因" * 30)
            self.assertLessEqual(len(infer_session_title(path)), 61)
