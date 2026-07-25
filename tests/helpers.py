from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def write_session(root: Path, session_id: str, user_text: str = "Hello", assistant_text: str = "Hi", cwd: str = "/old/project") -> Path:
    path = root / "sessions" / "2026" / "07" / "25" / f"rollout-2026-07-25T10-00-00-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"timestamp": "2026-07-25T10:00:00Z", "type": "session_meta", "payload": {"id": session_id, "session_id": session_id, "timestamp": "2026-07-25T10:00:00Z", "cwd": cwd, "source": "app", "model_provider": "openai", "cli_version": "1.0"}},
        {"timestamp": "2026-07-25T10:00:01Z", "type": "event_msg", "payload": {"type": "user_message", "message": user_text}},
        {"timestamp": "2026-07-25T10:00:02Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": assistant_text}]}},
        {"timestamp": "2026-07-25T10:00:03Z", "type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "secret"}},
    ]
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
    return path


def create_state_database(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "state_5.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE threads (
                id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL, source TEXT NOT NULL, model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL, title TEXT NOT NULL, sandbox_policy TEXT NOT NULL,
                approval_mode TEXT NOT NULL, tokens_used INTEGER NOT NULL DEFAULT 0,
                has_user_event INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
                archived_at INTEGER, cli_version TEXT NOT NULL DEFAULT '',
                first_user_message TEXT NOT NULL DEFAULT '', created_at_ms INTEGER,
                updated_at_ms INTEGER, thread_source TEXT, preview TEXT NOT NULL DEFAULT '',
                recency_at INTEGER NOT NULL DEFAULT 0, recency_at_ms INTEGER NOT NULL DEFAULT 0,
                history_mode TEXT NOT NULL DEFAULT 'legacy', memory_mode TEXT NOT NULL DEFAULT 'enabled',
                name TEXT
            )"""
        )
    return path
