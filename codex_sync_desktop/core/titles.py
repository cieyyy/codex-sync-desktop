from __future__ import annotations

import json
import re
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
    "import vs code chat session for browsing:",
    "[imported from vs code]",
    "imported conversation ",
)
REQUEST_MARKERS = (
    "## My request for Codex:",
    "## My request for ChatGPT:",
    "## My request:",
)


def title_candidate(text: str) -> str:
    candidate = str(text or "").strip()
    for marker in REQUEST_MARKERS:
        if marker in candidate:
            candidate = candidate.rsplit(marker, 1)[1].strip()
            break
    candidate = re.sub(r"<image\b[^>]*>.*?</image>", "", candidate, flags=re.S | re.I)
    candidate = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", candidate)
    compact = " ".join(candidate.split())
    return compact if is_usable_title(compact) else ""


def is_usable_title(value: str) -> bool:
    compact = " ".join(str(value or "").split()).strip()
    if not compact:
        return False
    lowered = compact.lower()
    return lowered not in {"vs code chat", "new chat", "新对话", "新建对话", "新建聊天"} and not any(
        lowered.startswith(prefix) for prefix in INVALID_TITLE_PREFIXES
    )


def _short_title(text: str) -> str:
    # Use the request's opening sentence, without copying logs or entire prompts.
    candidate = title_candidate(text)
    if not candidate or candidate.lower() in {"继续", "继续执行", "好的", "是", "ok", "yes", "continue"}:
        return ""
    candidate = re.split(r"[\n。！？]|(?<=[.!?])\s", candidate, maxsplit=1)[0]
    candidate = re.sub(r"^#+\s*", "", candidate).strip()
    return candidate[:60].rstrip() + ("…" if len(candidate) > 60 else "")


def _recovered_requests(value):
    """Read known VS Code request fields, never arbitrary state/tool strings."""
    if isinstance(value, dict):
        requests = value.get("requests")
        if isinstance(requests, list):
            for request in requests:
                if not isinstance(request, dict):
                    continue
                message = request.get("message")
                if isinstance(message, str):
                    yield message
                elif isinstance(message, dict) and isinstance(message.get("text"), str):
                    yield message["text"]
        for key, child in value.items():
            if key != "requests" and isinstance(child, (dict, list)):
                yield from _recovered_requests(child)
    elif isinstance(value, list):
        for child in value:
            yield from _recovered_requests(child)


def infer_session_title(path: Path, task_id: str = "") -> str:
    """Derive a local title from conversation text without a network/model call."""
    imported = False
    empty = False
    recovered_title = ""
    recovered_request = ""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                payload = record.get("payload") or {}
                if not isinstance(payload, dict):
                    continue
                if record.get("type") == "session_meta":
                    task_id = task_id or str(payload.get("id") or payload.get("session_id") or "")
                role = ""
                text = ""
                if record.get("type") == "event_msg" and payload.get("type") == "user_message":
                    role, text = "user", str(payload.get("message") or "")
                elif record.get("type") == "response_item" and payload.get("type") == "message":
                    role = payload.get("role")
                    text = "\n".join(str(block.get("text") or "") for block in payload.get("content") or []
                                     if isinstance(block, dict) and block.get("type") in {"input_text", "output_text"})
                if role == "user":
                    if text.lower().startswith("import vs code chat session for browsing:"):
                        imported = True
                        recovered_title = _short_title(text.split(":", 1)[1]) or recovered_title
                    else:
                        title = _short_title(text)
                        if title:
                            return title
                if role == "assistant" and text.startswith("# Imported VS Code chat data"):
                    imported = True
                    for block in re.findall(r"```json\s*\n(.*?)```", text, flags=re.S):
                        try:
                            data = json.loads(block)
                        except ValueError:
                            continue
                        if isinstance(data, dict):
                            empty = empty or data.get("is_empty") is True
                            recovered_title = _short_title(str(data.get("title") or "")) or recovered_title
                        for request in _recovered_requests(data):
                            recovered_request = recovered_request or _short_title(request)
    except OSError:
        return ""
    if recovered_request or recovered_title:
        return recovered_request or recovered_title
    suffix = f"（{task_id[:8]}）" if task_id else ""
    if imported:
        return ("VS Code 空会话" if empty else "VS Code 会话（仅元数据）") + suffix
    return "会话（无可用正文）" + suffix


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
