import json
import tempfile
import unittest
from pathlib import Path

from codex_sync_desktop.core.sessions import apply_import, export_sanitized_sessions, plan_import
from tests.helpers import write_session


class SessionSyncTests(unittest.TestCase):
    def test_export_and_import_with_conflict_quarantine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            source = write_session(source_home, session_id, "password=super-secret-value")
            report = export_sanitized_sessions(source_home, vault, "Office Mac")
            self.assertEqual(report.sessions, 1)
            self.assertGreaterEqual(report.secrets_redacted, 1)
            plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(plan.counts, {"copy": 1})
            result = apply_import(plan)
            self.assertEqual(len(result["copied"]), 1)
            imported = result["copied"][0]
            self.assertIn("[SECRET_REDACTED]", imported.read_text(encoding="utf-8"))
            self.assertNotIn("function_call", imported.read_text(encoding="utf-8"))

            source.write_text(source.read_text(encoding="utf-8") + json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "new"}}) + "\n", encoding="utf-8")
            export_sanitized_sessions(source_home, vault, "Office Mac")
            conflict_plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(conflict_plan.counts, {"conflict": 1})
            conflict_result = apply_import(conflict_plan)
            self.assertEqual(len(conflict_result["conflicts"]), 1)
            self.assertTrue(conflict_result["conflicts"][0].exists())

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


if __name__ == "__main__":
    unittest.main()
