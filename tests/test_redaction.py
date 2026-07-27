import unittest

from codex_sync_desktop.core.redaction import sanitize_record, sanitize_text


class RedactionTests(unittest.TestCase):
    def test_preserves_tokens_and_removes_media(self):
        text, media, secrets = sanitize_text("token ghp_abcdefghijklmnopqrstuvwxyz123456 and ![x](file:///tmp/a.png)")
        self.assertIn("ghp_abcdefghijklmnopqrstuvwxyz123456", text)
        self.assertIn("[image omitted]", text)
        self.assertEqual(media, 1)
        self.assertEqual(secrets, 0)

    def test_preserves_tool_calls(self):
        item, media, secrets = sanitize_record({"type": "response_item", "payload": {"type": "function_call"}})
        self.assertEqual(item["payload"]["type"], "function_call")
        self.assertEqual((media, secrets), (0, 0))


if __name__ == "__main__":
    unittest.main()
