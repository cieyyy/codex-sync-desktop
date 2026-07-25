import unittest

from codex_sync_desktop.core.redaction import sanitize_record, sanitize_text


class RedactionTests(unittest.TestCase):
    def test_redacts_tokens_and_media(self):
        text, media, secrets = sanitize_text("token ghp_abcdefghijklmnopqrstuvwxyz123456 and ![x](file:///tmp/a.png)")
        self.assertNotIn("ghp_", text)
        self.assertIn("[GITHUB_TOKEN_REDACTED]", text)
        self.assertIn("[media omitted]", text)
        self.assertEqual(media, 1)
        self.assertEqual(secrets, 1)

    def test_omits_tool_calls(self):
        item, media, secrets = sanitize_record({"type": "response_item", "payload": {"type": "function_call"}})
        self.assertIsNone(item)
        self.assertEqual((media, secrets), (0, 0))


if __name__ == "__main__":
    unittest.main()
