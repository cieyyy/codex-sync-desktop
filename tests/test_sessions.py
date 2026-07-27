import json
import tempfile
import unittest
from pathlib import Path

from codex_sync_desktop.core.sessions import apply_import, export_sanitized_sessions, plan_import
from tests.helpers import write_session


class SessionSyncTests(unittest.TestCase):
    def test_raw_destination_is_identical_to_its_sanitized_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            source = write_session(source_home, session_id, "Keep this text", "Answer")
            export_sanitized_sessions(source_home, vault, "Office Mac")
            destination = target_home / source.relative_to(source_home)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(plan.counts, {"identical": 1})

    def test_local_conversation_superset_is_not_a_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            source = write_session(source_home, session_id, "First question", "First answer")
            export_sanitized_sessions(source_home, vault, "Office Mac")
            destination = target_home / source.relative_to(source_home)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            with destination.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"timestamp": "2026-07-25T10:01:00Z", "type": "event_msg", "payload": {"type": "user_message", "message": "Follow-up"}}) + "\n")
            plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(plan.counts, {"identical": 1})

    def test_export_and_import_with_conflict_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            target_home = root / "target"
            vault = root / "vault"
            session_id = "019f9999-1111-7222-8333-444455556666"
            source = write_session(source_home, session_id, "password=super-secret-value")
            report = export_sanitized_sessions(source_home, vault, "Office Mac")
            self.assertEqual(report.sessions, 1)
            self.assertEqual(report.secrets_redacted, 0)
            plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(plan.counts, {"copy": 1})
            result = apply_import(plan)
            self.assertEqual(len(result["copied"]), 1)
            imported = result["copied"][0]
            self.assertIn("password=super-secret-value", imported.read_text(encoding="utf-8"))
            self.assertIn("function_call", imported.read_text(encoding="utf-8"))

            source.write_text(source.read_text(encoding="utf-8") + json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "new"}}) + "\n", encoding="utf-8")
            export_sanitized_sessions(source_home, vault, "Office Mac")
            conflict_plan = plan_import(target_home, vault, "office-mac")
            self.assertEqual(conflict_plan.counts, {"conflict": 1})
            conflict_result = apply_import(conflict_plan)
            self.assertEqual(len(conflict_result["conflicts"]), 1)
            self.assertEqual(len(conflict_result["merged"]), 1)
            self.assertTrue(conflict_result["conflicts"][0].exists())
            merged_text = conflict_result["merged"][0].read_text(encoding="utf-8")
            self.assertIn("super-secret-value", merged_text)
            self.assertIn('"message":"new"', merged_text)

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
