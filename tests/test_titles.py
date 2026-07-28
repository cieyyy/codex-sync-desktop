from unittest import TestCase

from codex_sync_desktop.core.titles import is_usable_title, title_candidate


class TitleQualityTests(TestCase):
    def test_rejects_injected_context_titles(self):
        self.assertFalse(is_usable_title("AGENTS.md instructions 你是我的运维助手"))
        self.assertFalse(is_usable_title("<environment_context> <cwd>D:\\project</cwd>"))

    def test_extracts_request_after_attachment_preamble(self):
        text = "# Files mentioned by the user:\n\n## My request for Codex:\n修复生产环境部署脚本"

        self.assertEqual(title_candidate(text), "修复生产环境部署脚本")
