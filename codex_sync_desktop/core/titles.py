from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .backups import find_state_databases, select_state_database


INVALID_TITLE_PREFIXES = (
    "# agents.md instructions",
    "agents.md instructions",
    "<environment_context>",
    "<recommended_plugins>",
    "<skills_instructions>",
    "<plugins_instructions>",
    "<app-context>",
    "<collaboration_mode>",
    "<personality_spec>",
    "<permissions instructions>",
    "# files mentioned by the user:",
    "# response annotations:",
)
REQUEST_MARKERS = (
    "## My request for Codex:",
    "## My request for ChatGPT:",
)


def title_candidate(text: str) -> str:
    candidate = str(text or "").strip()
    for marker in REQUEST_MARKERS:
        if marker in candidate:
            candidate = candidate.rsplit(marker, 1)[1].strip()
            break
    compact = " ".join(candidate.split())
    return compact if is_usable_title(compact) else ""


def is_usable_title(value: str) -> bool:
    compact = " ".join(str(value or "").split()).strip()
    if not compact:
        return False
    lowered = compact.lower()
    return not any(lowered.startswith(prefix) for prefix in INVALID_TITLE_PREFIXES)


def read_thread_titles(codex_home: Path) -> dict[str, str]:
    """Read titles from the side-bar index, then let the active database win."""
    index = codex_home / "session_index.jsonl"
    titles = _read_index_titles(index) if index.is_file() else {}
    databases = find_state_databases(codex_home)
    if databases:
        try:
            active = select_state_database(databases)
            titles.update(_read_database_titles(active))
        except OSError:
            pass
    return titles


def _read_index_titles(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        task_id = str(item.get("id") or "").strip()
        title = str(item.get("thread_name") or "").strip()
        if task_id and is_usable_title(title):
            result[task_id] = title
    return result


def _read_database_titles(path: Path) -> dict[str, str]:
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='threads'").fetchone():
                return {}
            return {
                str(task_id): str(title).strip()
                for task_id, title in connection.execute("SELECT id, title FROM threads")
                if task_id and title and is_usable_title(str(title))
            }
    except (OSError, sqlite3.Error):
        return {}
