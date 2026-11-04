from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping

from .config import device_slug
from .models import ExportReport, ImportItem, ImportPlan
from .projects import read_project_context, session_project, session_cwd, combine_projects, save_imported_projects, normalize_project
from .redaction import sanitize_record
from .titles import infer_session_title, is_usable_title, read_thread_titles


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


def open_session_text(path: Path):
    if path.name.endswith(".jsonl.zst"):
        try:
            import zstandard
        except ImportError as exc:
            raise RuntimeError("读取压缩归档需要安装项目依赖 zstandard") from exc
        return io.TextIOWrapper(zstandard.open(path, "rb"), encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def iter_export_session_files(codex_home: Path, include_archived: bool = False):
    yield from iter_active_session_files(codex_home)
    if include_archived:
        root = codex_home / "archived_sessions"
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file() and (path.name.endswith(".jsonl") or path.name.endswith(".jsonl.zst")):
                    # Prefer an uncompressed original if both versions exist.
                    if path.suffix == ".zst" and path.with_suffix("").exists():
                        continue
                    yield "archived_sessions", path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(_canonical_text_bytes(path.read_bytes())).hexdigest()


def _canonical_text_bytes(content: bytes) -> bytes:
    """Keep JSONL verification stable when Git converts checkout line endings."""
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def export_sanitized_sessions(codex_home: Path, vault: Path, device_name: str, include_archived: bool = False) -> ExportReport:
    if not (codex_home / "sessions").is_dir() and not (include_archived and (codex_home / "archived_sessions").is_dir()):
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

    project_context = read_project_context(codex_home)

    for root_name, source in iter_export_session_files(codex_home, include_archived):
        relative_in_root = source.relative_to(codex_home / root_name)
        if relative_in_root.suffix == ".zst":
            relative_in_root = relative_in_root.with_suffix("")
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
            "project": session_project(project_context, task_id, session_cwd(source)),
        }
        if result.get("original_model_provider"):
            entry["original_model_provider"] = result["original_model_provider"]
        if is_usable_title(titles.get(task_id, "")):
            entry["title"] = titles[task_id]
        else:
            entry["title"] = infer_session_title(destination, task_id)
        manifest_sessions.append(entry)

    report.removed_files = _remove_stale_exports(output_root, expected_outputs)
    report.changed_files += report.removed_files

    project_groups = {}
    for entry in manifest_sessions:
        project = entry['project']
        group = project_groups.setdefault(project['group_id'], dict(project, session_ids=[]))
        if entry['task_id'] not in group['session_ids']:
            group['session_ids'].append(entry['task_id'])
    manifest = {
        "format": 4,
        "project_metadata_format": 1,
        "projects": sorted(project_groups.values(), key=lambda project: project["group_id"]),
        "device": device_name,
        "device_slug": slug,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "include_archived": include_archived,
        "content": "all textual Codex session records and titles; inline media and binary attachments omitted; sensitive fields preserved" if include_archived else "active textual Codex session records and titles; archived sessions, inline media, and binary attachments omitted; sensitive fields preserved",
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
            "project": normalize_project(entry.get("project")) if entry.get("project") else combine_projects([], session_cwd(source)),
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
        if not source_title:
            source_title = local_title or infer_session_title(source, task_id)
            item_metadata["source_title"] = source_title
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


def repository_session_summary(vault: Path) -> tuple[int, str]:
    identities = set()
    latest = ""
    for device in list_source_devices(vault):
        data = json.loads((vault / "sessions-text/devices" / device / "manifest.json").read_text(encoding="utf-8"))
        latest = max(latest, str(data.get("exported_at") or ""))
        for entry in data.get("sessions", []):
            match = re.search(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", Path(entry["path"]).name, re.I)
            identities.add(match[0] if match else str(entry.get("task_id") or entry["path"]))
    return len(identities), latest


def imported_rollout_path(codex_home: Path, source: Path, identity: str) -> Path:
    """Keep the timestamp required by Codex's paginated rollout reader."""
    safe_id = identity if re.fullmatch(r"[\w-]+", identity) else hashlib.sha256(identity.encode()).hexdigest()
    for record in _read_records(source):
        if record.get("type") != "session_meta":
            continue
        raw = str((record.get("payload") or {}).get("timestamp") or record.get("timestamp") or "")
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%dT%H-%M-%S")
        except ValueError:
            break
        return codex_home / "sessions/synced" / f"rollout-{stamp}-{safe_id}.jsonl"
    match = re.match(r"rollout-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-", source.name)
    if match:
        return codex_home / "sessions/synced" / f"rollout-{match[1]}-{safe_id}.jsonl"
    raise ValueError(f"会话缺少有效创建时间，无法生成 Codex 可读取的文件名：{identity}")


def standalone_import_records(records: list[Dict[str, Any]], sources: Iterable[Path]) -> list[Dict[str, Any]]:
    """Detach merged history from source byte offsets only when its sources exist."""
    available = set()
    bases = set()
    has_root = False
    paginated = False
    for source in sources:
        available.update(re.findall(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", source.name, re.I))
        for record in _read_records(source):
            if record.get("type") != "session_meta":
                continue
            payload = record.get("payload") or {}
            paginated = paginated or payload.get("history_mode") == "paginated"
            available.add(str(payload.get("id") or ""))
            base = payload.get("history_base") or {}
            if base.get("thread_id"):
                bases.add(str(base["thread_id"]))
            else:
                has_root = True
    if bases - available:
        raise ValueError("会话历史分片不完整，已停止导入：" + ", ".join(sorted(bases - available)))
    if bases and not has_root:
        raise ValueError("会话历史缺少起始分片，已停止导入")
    result = []
    for ordinal, record in enumerate(records):
        if paginated:
            record = {**record, "ordinal": ordinal}
        if record.get("type") == "session_meta":
            payload = dict(record.get("payload") or {})
            payload["history_mode"] = "paginated" if paginated else "legacy"
            payload.pop("history_base", None)
            record = {**record, "payload": payload}
        result.append(record)
    return result


def plan_all_import(codex_home: Path, vault: Path, progress: Callable[[str], None] | None = None,
                    *, activity_since: float | None = None, activity_before: float | None = None) -> ImportPlan:
    """Verify all sources, then produce one reversible import item per real session ID."""
    plan = ImportPlan(source_device="all", source_label="全部会话（仅新增，保护本机）")
    groups = {}
    project_records = {}
    verified_count = 0
    for device in list_source_devices(vault):
        device_root = vault / "sessions-text/devices" / device
        manifest = json.loads((device_root / "manifest.json").read_text(encoding="utf-8"))
        entries = manifest.get("sessions")
        if not isinstance(entries, list):
            raise ValueError(f"Invalid manifest: {device_root}")
        for entry in entries:
            verified_count += 1
            if progress and verified_count % 20 == 0:
                progress(f"正在校验仓库会话记录：{verified_count} 条")
            relative = _safe_relative(str(entry.get("path", "")))
            source, destination = _resolve_manifest_paths(device_root / "sessions", codex_home, relative,
                                                          int(manifest.get("format", 1)))
            if not source.is_file():
                plan.items.append(ImportItem("missing-source", relative, source, destination))
                continue
            digest = sha256_file(source)
            if entry.get("sha256") and digest != entry["sha256"]:
                plan.items.append(ImportItem("invalid-source-hash", relative, source, destination,
                                             detail="会话文件校验失败"))
                continue
            identity = _session_id_from_file(source)
            if entry.get("project"):
                project_records.setdefault(identity, []).append(entry["project"])
            groups.setdefault(identity, []).append((source, digest, str(entry.get("title") or ""),
                                                     str(manifest.get("exported_at") or "")))

    local_titles = read_thread_titles(codex_home)
    reviewed = {}
    catalog_path = vault / "sessions-text/title-catalog.json"
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        reviewed = {item["task_id"]: item["title"] for item in catalog.get("items", [])
                    if is_usable_title(item.get("title", ""))}
    local = existing_session_ids(codex_home)
    from .time_filter import last_activity

    for position, (identity, copies) in enumerate(sorted(groups.items()), 1):
        if progress:
            progress(f"正在合并会话：{position}/{len(groups)}")
        copies.sort(key=lambda copy: (copy[3], str(copy[0])), reverse=True)
        source = copies[0][0]
        project = combine_projects(project_records.get(identity, []), session_cwd(source))
        if identity in local:
            destination = local[identity] or codex_home / "sessions/synced" / f"rollout-{identity}.jsonl"
            plan.items.append(ImportItem(
                "skipped-existing", str(destination), source, destination,
                detail="已保护本机会话：保留正文、标题、项目归属和工作目录",
                task_id=identity, local_title=local_titles.get(identity, ""), project=project,
            ))
            continue
        if activity_since is not None or activity_before is not None:
            activities = [last_activity(_read_records(path)) for path, _, _, _ in copies]
            latest = max((value for value in activities if value is not None), default=None)
            if latest is None or (activity_since is not None and latest < activity_since) or (activity_before is not None and latest >= activity_before):
                safe_id = identity if re.fullmatch(r"[\w-]+", identity) else hashlib.sha256(identity.encode()).hexdigest()
                destination = codex_home / "sessions/synced" / f"rollout-{safe_id}.jsonl"
                title = reviewed.get(identity) or next((title for _, _, title, _ in copies if is_usable_title(title)), "")
                reason = "无有效活动时间，未纳入日期范围" if latest is None else "最后活动：" + datetime.fromtimestamp(latest).astimezone().strftime("%Y-%m-%d %H:%M") + "，不在所选范围内"
                plan.items.append(ImportItem("skipped-time", str(destination), source, destination,
                                            detail=reason, task_id=identity, source_title=title, activity_at=latest, project=project))
                continue
        incoming = _read_records(source)
        seen = {copies[0][1]}
        for path, digest, _, _ in copies[1:]:
            if digest in seen:
                continue
            encoded, _ = _merge_records(incoming, _read_records(path))
            incoming = [json.loads(line) for line in encoded.splitlines()]
            seen.add(digest)
        incoming = standalone_import_records(incoming, (copy[0] for copy in copies))
        incoming_bytes = b"".join((json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
                                  for record in incoming)
        destination = imported_rollout_path(codex_home, source, identity)
        if destination.exists():
            raise FileExistsError(f"导入目标已存在，已停止以保护本机文件：{destination}")
        action = "copy"
        title = reviewed.get(identity) or next((title for _, _, title, _ in copies if is_usable_title(title)), "")
        title = title or local_titles.get(identity) or infer_session_title(source, identity)
        if title != local_titles.get(identity):
            plan.title_updates[identity] = title
        plan.items.append(ImportItem(
            action, destination.relative_to(codex_home).as_posix(), source, destination,
            merged_content=incoming_bytes,
            detail=f"已合并 {len(copies)} 份仓库记录" if len(copies) > 1 else "仓库会话",
            task_id=identity, source_title=title, local_title=local_titles.get(identity, ""),
            incoming_content=incoming_bytes, activity_at=last_activity(incoming), project=project,
        ))
    return plan


def existing_session_ids(codex_home: Path, include_files: bool = True) -> dict[str, Path | None]:
    """Read every local identity store; fail closed on unreadable databases/indexes."""
    import sqlite3
    from contextlib import closing
    from .backups import find_state_databases

    result = {}
    if include_files:
        for folder in ("sessions", "archived_sessions"):
            for path in (codex_home / folder).rglob("*"):
                if not path.is_file() or not path.name.endswith((".jsonl", ".jsonl.zst")):
                    continue
                # Verify readability rather than treating a read failure as absence.
                with open_session_text(path) as handle:
                    handle.read(1)
                result[_session_id_from_file(path)] = path
                match = re.search(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", path.name)
                if match:
                    result.setdefault(match.group(), path)
    index = codex_home / "session_index.jsonl"
    if index.exists():
        for line in index.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("id"):
                result.setdefault(str(row["id"]), None)
    for database in find_state_databases(codex_home):
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, column in (("threads", "id"), ("local_thread_catalog", "thread_id")):
                if table in tables:
                    for row in connection.execute(f"SELECT {column} FROM {table}"):
                        result.setdefault(str(row[0]), None)
    return result


def apply_import(plan: ImportPlan) -> Dict[str, Any]:
    invalid = [item for item in plan.items if item.action in ("missing-source", "invalid-source-hash")]
    if invalid:
        raise ValueError(f"Import source verification failed for {len(invalid)} file(s)")
    if plan.source_device == "all":
        copies = [item for item in plan.items if item.action == "copy"]
        if copies:
            home = copies[0].destination.parents[2]
            existing = existing_session_ids(home)
            if any(item.task_id in existing or item.destination.exists() for item in copies):
                raise FileExistsError("本机会话已变化，请重新预览；为保护已有会话，本次导入已停止")
    copied = []
    conflicts = []
    merged = []
    for item in plan.items:
        if item.action == "copy":
            if item.merged_content is not None:
                _write_atomic(item.destination, item.merged_content)
            else:
                _copy_atomic(item.source, item.destination)
            copied.append(item.destination)
        elif item.action == "conflict":
            if item.merged_content is None:
                raise ValueError(f"Missing merge data for {item.relative_path}")
            _write_atomic(item.destination, item.merged_content)
            merged.append(item.destination)
    if plan.source_device == "all" and copied:
        save_imported_projects(home, [item for item in copies if item.destination in copied])
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
    original_model_provider = ""
    with open_session_text(source) as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            try:
                item = json.loads(raw_line)
            except ValueError:
                invalid += 1
                continue
            if item.get("type") == "session_meta" and not original_model_provider:
                original_model_provider = str((item.get("payload") or {}).get("model_provider") or "").strip()
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
        "original_model_provider": original_model_provider,
    }


def _merge_session_bytes(destination: Path, source: Path) -> tuple[bytes, Dict[str, int]]:
    destination_records = _read_records(destination)
    source_records = _read_records(source)
    return _merge_records(destination_records, source_records)


def _merge_records(destination_records, source_records) -> tuple[bytes, Dict[str, int]]:
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
        with open_session_text(path) as handle:
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
