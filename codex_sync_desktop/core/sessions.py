from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping

from .config import device_slug
from .models import ExportReport, ImportItem, ImportPlan
from .redaction import sanitize_record
from .titles import is_usable_title, read_thread_titles


class NoActiveSessionsError(FileNotFoundError):
    def __init__(self, sessions_path: Path):
        self.sessions_path = sessions_path
        super().__init__(
            "尚未发现 Codex 会话文件。请先打开 ChatGPT/Codex，使用 Codex 完成至少一次对话，"
            f"系统创建 {sessions_path} 后再进行同步。"
        )


def iter_session_files(codex_home: Path) -> Iterator[tuple[str, Path]]:
    for root_name in ("sessions", "archived_sessions"):
        root = codex_home / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            relative = path.relative_to(root)
            if path.is_file() and (not relative.parts or relative.parts[0] not in ("sessions", "archived_sessions")):
                yield root_name, path


def iter_active_session_files(codex_home: Path) -> Iterator[tuple[str, Path]]:
    root = codex_home / "sessions"
    if not root.exists():
        return
    for path in sorted(root.rglob("*.jsonl")):
        if path.is_file():
            yield "sessions", path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(_canonical_text_bytes(path.read_bytes())).hexdigest()


def _canonical_text_bytes(content: bytes) -> bytes:
    """Keep JSONL verification stable when Git converts checkout line endings."""
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def export_sanitized_sessions(codex_home: Path, vault: Path, device_name: str) -> ExportReport:
    if not (codex_home / "sessions").is_dir():
        raise NoActiveSessionsError(codex_home / "sessions")
    slug = device_slug(device_name)
    device_root = vault / "sessions-text" / "devices" / slug
    legacy_device_roots = _matching_legacy_device_roots(vault, device_name, slug)
    output_root = device_root / "sessions"
    output_root.mkdir(parents=True, exist_ok=True)
    report = ExportReport(device=device_name, output=device_root)
    manifest_sessions = []
    expected_outputs: set[Path] = set()
    titles = read_thread_titles(codex_home)

    for root_name, source in iter_active_session_files(codex_home):
        relative_in_root = source.relative_to(codex_home / root_name)
        manifest_path = (Path(root_name) / relative_in_root).as_posix()
        destination = output_root / root_name / relative_in_root
        expected_outputs.add(destination.resolve())
        result = _sanitize_file(source, destination)
        report.sessions += 1
        report.source_bytes += source.stat().st_size
        report.output_bytes += result["bytes"]
        report.kept_lines += result["kept"]
        report.omitted_lines += result["omitted"]
        report.invalid_lines += result["invalid"]
        report.media_removed += result["media"]
        report.secrets_redacted += result["secrets"]
        report.changed_files += int(result["changed"])
        task_id = _session_id_from_file(source)
        entry = {
            "path": manifest_path,
            "task_id": task_id,
            "sha256": result["sha256"],
            "bytes": result["bytes"],
        }
        if is_usable_title(titles.get(task_id, "")):
            entry["title"] = titles[task_id]
        manifest_sessions.append(entry)

    report.removed_files = _remove_stale_exports(output_root, expected_outputs)
    report.changed_files += report.removed_files

    manifest = {
        "format": 4,
        "device": device_name,
        "device_slug": slug,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "content": "active textual Codex session records and titles; archived sessions, inline media, and binary attachments omitted; sensitive fields preserved",
        "conflict_policy": "merge by semantic content and timestamp; preserve richer duplicate records",
        "sessions": manifest_sessions,
    }
    manifest_path = device_root / "manifest.json"
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    report.changed_files += int(_write_if_changed(manifest_path, encoded.encode("utf-8")))
    for legacy_root in legacy_device_roots:
        report.changed_files += sum(1 for path in legacy_root.rglob("*") if path.is_file())
        shutil.rmtree(legacy_root)
    return report


def _matching_legacy_device_roots(vault: Path, device_name: str, current_slug: str) -> list[Path]:
    devices_root = vault / "sessions-text" / "devices"
    if not devices_root.is_dir():
        return []
    matches: list[Path] = []
    normalized_name = device_name.strip()
    for candidate in devices_root.iterdir():
        if not candidate.is_dir() or candidate.name == current_slug:
            continue
        manifest_path = candidate / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if str(manifest.get("device") or "").strip() == normalized_name:
            matches.append(candidate)
    return matches


def list_source_devices(vault: Path) -> list[str]:
    root = vault / "sessions-text" / "devices"
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and (path / "manifest.json").is_file())


def list_source_device_options(vault: Path) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    used_labels: set[str] = set()
    for key in list_source_devices(vault):
        manifest_path = vault / "sessions-text" / "devices" / key / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            manifest = {}
        label = str(manifest.get("device") or key).strip() or key
        if label in used_labels:
            label = f"{label} ({key})"
        used_labels.add(label)
        options.append((label, key))
    return options


def plan_import(codex_home: Path, vault: Path, source_device: str) -> ImportPlan:
    device_root = vault / "sessions-text" / "devices" / source_device
    manifest_path = device_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("sessions")
    if not isinstance(entries, list):
        raise ValueError(f"Invalid manifest: {manifest_path}")
    format_version = int(manifest.get("format", 1))
    source_root = device_root / "sessions"
    source_label = str(manifest.get("device") or source_device).strip() or source_device
    plan = ImportPlan(source_device=source_device, source_label=source_label)
    local_titles = read_thread_titles(codex_home)

    for entry in entries:
        relative = _safe_relative(str(entry.get("path", "")))
        source, destination = _resolve_manifest_paths(source_root, codex_home, relative, format_version)
        task_id = str(entry.get("task_id") or "").strip()
        source_title = str(entry.get("title") or "").strip()[:500]
        if not is_usable_title(source_title):
            source_title = ""
        local_title = local_titles.get(task_id, "") if task_id else ""
        item_metadata = {
            "task_id": task_id,
            "source_title": source_title,
            "local_title": local_title,
        }
        if not source.exists():
            plan.items.append(ImportItem("missing-source", relative, source, destination, **item_metadata))
            continue
        actual_hash = sha256_file(source)
        expected_hash = str(entry.get("sha256", ""))
        if expected_hash and actual_hash != expected_hash:
            plan.items.append(ImportItem(
                "invalid-source-hash",
                relative,
                source,
                destination,
                detail=f"expected {expected_hash}, got {actual_hash}",
                **item_metadata,
            ))
            continue
        if task_id and source_title and local_titles.get(task_id) != source_title:
            plan.title_updates[task_id] = source_title
        if not destination.exists():
            plan.items.append(ImportItem("copy", relative, source, destination, **item_metadata))
            continue
        if (
            sha256_file(destination) == actual_hash
            or sanitized_sha256_file(destination) == actual_hash
            or conversation_is_prefix(source, destination)
        ):
            plan.items.append(ImportItem("identical", relative, source, destination, **item_metadata))
            continue
        merged_content, merge = _merge_session_bytes(destination, source)
        if merge["changes_from_source"] == 0:
            plan.items.append(ImportItem(
                "identical",
                relative,
                source,
                destination,
                detail="semantic match",
                **item_metadata,
            ))
            continue
        plan.items.append(ImportItem(
            "conflict", relative, source, destination,
            merged_content=merged_content,
            detail=f"merge {merge['source_additions']} additions and {merge['source_replacements']} richer records",
            **item_metadata,
        ))
    return plan


def apply_import(plan: ImportPlan) -> Dict[str, Any]:
    invalid = [item for item in plan.items if item.action in ("missing-source", "invalid-source-hash")]
    if invalid:
        raise ValueError(f"Import source verification failed for {len(invalid)} file(s)")
    copied = []
    conflicts = []
    merged = []
    for item in plan.items:
        if item.action == "copy":
            _copy_atomic(item.source, item.destination)
            copied.append(item.destination)
        elif item.action == "conflict":
            if item.merged_content is None:
                raise ValueError(f"Missing merge data for {item.relative_path}")
            _write_atomic(item.destination, item.merged_content)
            merged.append(item.destination)
    return {"copied": copied, "conflicts": conflicts, "merged": merged, "counts": plan.counts}


def _sanitize_file(source: Path, destination: Path) -> Dict[str, Any]:
    encoded, result = _sanitized_bytes(source)
    result["changed"] = _write_if_changed(destination, encoded)
    return result


def sanitized_sha256_file(source: Path) -> str:
    encoded, _ = _sanitized_bytes(source)
    return hashlib.sha256(encoded).hexdigest()


def conversation_is_prefix(source: Path, destination: Path) -> bool:
    incoming = conversation_signature(source)
    local = conversation_signature(destination)
    return bool(incoming) and len(incoming) <= len(local) and incoming == local[:len(incoming)]


def conversation_signature(path: Path) -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            try:
                item = json.loads(raw_line)
            except ValueError:
                continue
            payload = item.get("payload") or {}
            role = ""
            text = ""
            if item.get("type") == "event_msg" and payload.get("type") in ("user_message", "agent_message"):
                role = "user" if payload["type"] == "user_message" else "assistant"
                text = str(payload.get("message") or "").strip()
            elif item.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") in ("user", "assistant"):
                role = str(payload["role"])
                text = "\n".join(
                    str(block.get("text") or "")
                    for block in payload.get("content") or []
                    if block.get("type") in ("input_text", "output_text")
                ).strip()
            if not text:
                continue
            message = (role, text)
            if not messages or messages[-1] != message:
                messages.append(message)
    return messages


def _sanitized_bytes(source: Path) -> tuple[bytes, Dict[str, Any]]:
    lines = []
    kept = omitted = invalid = media = secrets = 0
    with source.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            try:
                item = json.loads(raw_line)
            except ValueError:
                invalid += 1
                continue
            clean, media_count, secret_count = sanitize_record(item)
            media += media_count
            secrets += secret_count
            if clean is None:
                omitted += 1
                continue
            lines.append(json.dumps(clean, ensure_ascii=False, separators=(",", ":")) + "\n")
            kept += 1
    encoded = "".join(lines).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return encoded, {
        "bytes": len(encoded), "sha256": digest,
        "kept": kept, "omitted": omitted, "invalid": invalid,
        "media": media, "secrets": secrets,
    }


def _merge_session_bytes(destination: Path, source: Path) -> tuple[bytes, Dict[str, int]]:
    destination_records = _read_records(destination)
    source_records = _read_records(source)
    merged = [{"item": item, "sequence": index} for index, item in enumerate(destination_records)]
    matches: Dict[str, list[int]] = {}
    for index, record in enumerate(merged):
        matches.setdefault(_semantic_key(record["item"]), []).append(index)

    source_additions = 0
    source_replacements = 0
    sequence = len(merged)
    for item in source_records:
        key = _semantic_key(item)
        indexes = matches.get(key) or []
        if not indexes:
            merged.append({"item": item, "sequence": sequence})
            sequence += 1
            source_additions += 1
            continue
        index = indexes.pop(0)
        existing = merged[index]
        if _record_size(item) > _record_size(existing["item"]):
            merged[index] = {"item": item, "sequence": existing["sequence"]}
            source_replacements += 1

    merged.sort(key=lambda record: _record_sort_key(record["item"], record["sequence"]))
    encoded = "".join(
        json.dumps(record["item"], ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in merged
    ).encode("utf-8")
    return encoded, {
        "source_additions": source_additions,
        "source_replacements": source_replacements,
        "changes_from_source": source_additions + source_replacements,
    }


def _read_records(path: Path) -> list[Dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                records.append(item)
    return records


def _semantic_key(item: Dict[str, Any]) -> str:
    payload = item.get("payload") or {}
    timestamp = str(item.get("timestamp") or payload.get("timestamp") or "")
    item_type = str(item.get("type") or "")
    payload_type = str(payload.get("type") or "")
    if item_type == "session_meta":
        return "session_meta"
    if item_type == "event_msg" and payload_type in ("user_message", "agent_message"):
        return _stable_json([timestamp or payload.get("message"), item_type, payload_type])
    if item_type == "response_item" and payload_type == "message":
        content = payload.get("content") or []
        text = "\n".join(str(block.get("text") or block.get("content") or "") for block in content if isinstance(block, dict))
        return _stable_json([timestamp or text, item_type, payload_type, payload.get("role")])
    if "call_id" in payload:
        return _stable_json([
            timestamp, item_type, payload_type, payload.get("call_id"),
            payload.get("name"), payload.get("arguments"), payload.get("output"),
        ])
    return _stable_json(item)


def _record_sort_key(item: Dict[str, Any], sequence: int) -> tuple[int, float, int]:
    metadata = 0 if item.get("type") == "session_meta" else 1
    raw = item.get("timestamp") or (item.get("payload") or {}).get("timestamp") or ""
    try:
        timestamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        timestamp = float("inf")
    return metadata, timestamp, sequence


def _record_size(item: Dict[str, Any]) -> int:
    return len(_stable_json(item).encode("utf-8"))


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_if_changed(destination: Path, content: bytes) -> bool:
    if destination.exists() and destination.read_bytes() == content:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".tmp")
    temp.write_bytes(content)
    temp.replace(destination)
    return True


def _write_atomic(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".merge")
    temp.write_bytes(content)
    temp.replace(destination)


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".incoming")
    shutil.copy2(source, temp)
    temp.replace(destination)


def _remove_stale_exports(output_root: Path, expected: set[Path]) -> int:
    removed = 0
    for path in output_root.rglob("*.jsonl"):
        if path.is_file() and path.resolve() not in expected:
            path.unlink()
            removed += 1
    directories = sorted((path for path in output_root.rglob("*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True)
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass
    return removed


def _safe_relative(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/")
    parts = normalized.split("/")
    if not normalized or ".." in parts or any(part in ("", ".") for part in parts):
        raise ValueError(f"Unsafe manifest path: {value}")
    return normalized


def _resolve_manifest_paths(source_root: Path, codex_home: Path, relative: str, format_version: int) -> tuple[Path, Path]:
    if format_version >= 2:
        return source_root / relative, codex_home / relative
    return source_root / relative, codex_home / "sessions" / relative


def _task_id_from_filename(name: str) -> str:
    stem = name[:-6] if name.endswith(".jsonl") else name
    return stem.rsplit("-", 1)[-1] if "-" in stem else stem


def _session_id_from_file(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                try:
                    item = json.loads(raw_line)
                except ValueError:
                    continue
                if item.get("type") != "session_meta":
                    continue
                payload = item.get("payload") or {}
                task_id = str(payload.get("id") or payload.get("session_id") or "").strip()
                if task_id:
                    return task_id
    except OSError:
        pass
    return _task_id_from_filename(path.name)
