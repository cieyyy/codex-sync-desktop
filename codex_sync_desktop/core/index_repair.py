from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from .backups import create_consistent_backup, find_state_databases, select_state_database
from .models import RepairReport, SessionInfo
from .pathmap import map_path
from .sessions import iter_session_files


def parse_session(path: Path, codex_home: Path, mappings: Mapping[str, str] | None = None) -> SessionInfo | None:
    metadata: Dict[str, Any] = {}
    first_user = ""
    last_timestamp = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                try:
                    item = json.loads(raw_line)
                except ValueError:
                    continue
                timestamp = str(item.get("timestamp") or "")
                if timestamp > last_timestamp:
                    last_timestamp = timestamp
                payload = item.get("payload") or {}
                if item.get("type") == "session_meta" and not metadata:
                    metadata = payload
                if not first_user:
                    first_user = _extract_user_text(item)
    except OSError:
        return None
    session_id = str(metadata.get("id") or metadata.get("session_id") or "")
    if not session_id:
        return None
    created_iso = str(metadata.get("timestamp") or last_timestamp)
    created_at = _timestamp_seconds(created_iso, int(path.stat().st_mtime))
    updated_at = _timestamp_seconds(last_timestamp, int(path.stat().st_mtime))
    title = _clean_title(first_user) or f"Imported conversation {session_id[:8]}"
    cwd = map_path(str(metadata.get("cwd") or str(Path.home())), mappings or {})
    try:
        relative = path.relative_to(codex_home).as_posix()
    except ValueError:
        relative = path.name
    return SessionInfo(
        session_id=session_id,
        path=path.resolve(),
        relative_path=relative,
        created_at=created_at,
        updated_at=max(created_at, updated_at),
        cwd=cwd,
        title=title,
        preview=first_user.strip()[:1000] or title,
        source=str(metadata.get("source") or "app"),
        model_provider=str(metadata.get("model_provider") or "openai"),
        cli_version=str(metadata.get("cli_version") or ""),
        archived="archived_sessions" in path.parts,
    )


def repair_indexes(
    codex_home: Path,
    mappings: Mapping[str, str] | None = None,
    create_backup: bool = True,
    preferred_titles: Mapping[str, str] | None = None,
) -> RepairReport:
    report = RepairReport()
    sessions = []
    for _, path in iter_session_files(codex_home):
        info = parse_session(path, codex_home, mappings)
        report.scanned += 1
        if info:
            sessions.append(info)
        else:
            report.skipped += 1
    sessions, duplicate_count = _select_canonical_sessions(sessions)
    if duplicate_count:
        report.warnings.append(
            f"发现 {duplicate_count} 个同会话 ID 的额外文件；侧栏按活动状态、内容完整度和更新时间选择代表文件，原文件均保留"
        )
    databases = [path for path in find_state_databases(codex_home) if _has_threads_table(path)]
    if not databases:
        raise FileNotFoundError(f"No Codex state database with a threads table found in {codex_home}")
    if create_backup:
        report.backup_dir = create_consistent_backup(codex_home)
    database = _select_database(databases)
    existing_names = _read_existing_names(codex_home / "session_index.jsonl")
    with closing(sqlite3.connect(str(database))) as connection:
        connection.row_factory = sqlite3.Row
        db_names = {row["id"]: row["title"] for row in connection.execute("SELECT id, title FROM threads")}
        existing_names.update({key: value for key, value in db_names.items() if value})
        imported_names = {str(key): str(value).strip() for key, value in (preferred_titles or {}).items() if str(value).strip()}
        resolved_names: Dict[str, str] = {}
        columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
        for session in sessions:
            preferred_title = imported_names.get(session.session_id) or existing_names.get(session.session_id, session.title)
            session.title = preferred_title
            resolved_names[session.session_id] = preferred_title
            if session.session_id in db_names:
                report.updated += _update_existing(connection, columns, session)
            else:
                if _insert_thread(connection, columns, session):
                    report.inserted += 1
                else:
                    report.updated += _update_existing(connection, columns, session)
                db_names[session.session_id] = session.title
        connection.commit()
    _write_session_index(codex_home / "session_index.jsonl", sessions, resolved_names)
    report.index_entries = len(sessions)
    if len(databases) > 1:
        report.warnings.append(f"Updated {database.name}; found {len(databases)} databases with threads tables")
    return report


def _insert_thread(connection: sqlite3.Connection, columns: set[str], session: SessionInfo) -> bool:
    values: Dict[str, Any] = {
        "id": session.session_id,
        "rollout_path": str(session.path),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "source": session.source,
        "model_provider": session.model_provider,
        "cwd": session.cwd,
        "title": session.title,
        "sandbox_policy": '{"type":"disabled"}',
        "approval_mode": "never",
        "tokens_used": 0,
        "has_user_event": 1 if session.preview else 0,
        "archived": int(session.archived),
        "archived_at": session.updated_at if session.archived else None,
        "cli_version": session.cli_version,
        "first_user_message": session.preview,
        "memory_mode": "enabled",
        "created_at_ms": session.created_at * 1000,
        "updated_at_ms": session.updated_at * 1000,
        "thread_source": "imported",
        "preview": session.preview,
        "recency_at": session.updated_at,
        "recency_at_ms": session.updated_at * 1000,
        "history_mode": "legacy",
        "name": session.title,
    }
    selected = {key: value for key, value in values.items() if key in columns}
    names = ", ".join(selected)
    placeholders = ", ".join("?" for _ in selected)
    cursor = connection.execute(
        f"INSERT INTO threads ({names}) VALUES ({placeholders}) ON CONFLICT(id) DO NOTHING",
        tuple(selected.values()),
    )
    return cursor.rowcount == 1


def _select_canonical_sessions(sessions: Iterable[SessionInfo]) -> tuple[list[SessionInfo], int]:
    selected: Dict[str, SessionInfo] = {}
    total = 0
    for session in sessions:
        total += 1
        current = selected.get(session.session_id)
        if current is None or _canonical_score(session) > _canonical_score(current):
            selected[session.session_id] = session
    result = sorted(selected.values(), key=lambda item: (item.updated_at, item.session_id, str(item.path)))
    return result, total - len(result)


def _canonical_score(session: SessionInfo) -> tuple[int, int, int, str]:
    try:
        content_bytes = session.path.stat().st_size
    except OSError:
        content_bytes = 0
    return (
        1 if not session.archived else 0,
        content_bytes,
        session.updated_at,
        str(session.path),
    )


def _update_existing(connection: sqlite3.Connection, columns: set[str], session: SessionInfo) -> int:
    allowed = {
        "rollout_path": str(session.path), "cwd": session.cwd, "updated_at": session.updated_at,
        "updated_at_ms": session.updated_at * 1000, "recency_at": session.updated_at,
        "recency_at_ms": session.updated_at * 1000, "title": session.title, "name": session.title,
    }
    selected = {key: value for key, value in allowed.items() if key in columns}
    if not selected:
        return 0
    assignments = ", ".join(f"{key} = ?" for key in selected)
    cursor = connection.execute(f"UPDATE threads SET {assignments} WHERE id = ?", (*selected.values(), session.session_id))
    return 1 if cursor.rowcount else 0


def _write_session_index(path: Path, sessions: Iterable[SessionInfo], existing_names: Mapping[str, str]) -> None:
    entries = []
    for session in sessions:
        entries.append({
            "id": session.session_id,
            "thread_name": existing_names.get(session.session_id, session.title),
            "updated_at": datetime.fromtimestamp(session.updated_at, timezone.utc).isoformat().replace("+00:00", "Z"),
        })
    entries.sort(key=lambda item: (item["updated_at"], item["id"]))
    encoded = "".join(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n" for entry in entries)
    temp = path.with_suffix(".tmp")
    temp.write_text(encoded, encoding="utf-8")
    temp.replace(path)


def _read_existing_names(path: Path) -> Dict[str, str]:
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("id") and item.get("thread_name"):
            result[str(item["id"])] = str(item["thread_name"])
    return result


def _select_database(paths: list[Path]) -> Path:
    return select_state_database(paths)


def _has_threads_table(path: Path) -> bool:
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
            row = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='threads'").fetchone()
            return row is not None
    except sqlite3.Error:
        return False


def _extract_user_text(item: Mapping[str, Any]) -> str:
    payload = item.get("payload") or {}
    if item.get("type") == "event_msg" and payload.get("type") == "user_message":
        return str(payload.get("message") or "").strip()
    if item.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
        return "\n".join(str(block.get("text") or "") for block in payload.get("content") or [] if block.get("type") == "input_text").strip()
    return ""


def _clean_title(text: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return ""
    return compact[:80] + ("..." if len(compact) > 80 else "")


def _timestamp_seconds(value: str, fallback: int) -> int:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(parsed.timestamp())
    except ValueError:
        return fallback
