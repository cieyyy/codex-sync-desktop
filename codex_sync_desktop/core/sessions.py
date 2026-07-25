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


def iter_session_files(codex_home: Path) -> Iterator[tuple[str, Path]]:
    for root_name in ("sessions", "archived_sessions"):
        root = codex_home / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            if path.is_file():
                yield root_name, path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_sanitized_sessions(codex_home: Path, vault: Path, device_name: str) -> ExportReport:
    slug = device_slug(device_name)
    device_root = vault / "sessions-text" / "devices" / slug
    output_root = device_root / "sessions"
    output_root.mkdir(parents=True, exist_ok=True)
    report = ExportReport(device=device_name, output=device_root)
    manifest_sessions = []

    for root_name, source in iter_session_files(codex_home):
        relative_in_root = source.relative_to(codex_home / root_name)
        manifest_path = (Path(root_name) / relative_in_root).as_posix()
        destination = output_root / root_name / relative_in_root
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
        manifest_sessions.append({
            "path": manifest_path,
            "task_id": _task_id_from_filename(source.name),
            "sha256": result["sha256"],
            "bytes": result["bytes"],
        })

    manifest = {
        "format": 2,
        "device": device_name,
        "device_slug": slug,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "content": "user/assistant text and minimal session metadata; media, tools, credentials, and internal reasoning omitted",
        "sessions": manifest_sessions,
    }
    manifest_path = device_root / "manifest.json"
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    report.changed_files += int(_write_if_changed(manifest_path, encoded.encode("utf-8")))
    return report


def list_source_devices(vault: Path) -> list[str]:
    root = vault / "sessions-text" / "devices"
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and (path / "manifest.json").is_file())


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
    conflict_root = codex_home / "import-conflicts" / _timestamp_slug() / source_device
    plan = ImportPlan(source_device=source_device)

    for entry in entries:
        relative = _safe_relative(str(entry.get("path", "")))
        source, destination = _resolve_manifest_paths(source_root, codex_home, relative, format_version)
        if not source.exists():
            plan.items.append(ImportItem("missing-source", relative, source, destination))
            continue
        actual_hash = sha256_file(source)
        expected_hash = str(entry.get("sha256", ""))
        if expected_hash and actual_hash != expected_hash:
            plan.items.append(ImportItem("invalid-source-hash", relative, source, destination, detail=f"expected {expected_hash}, got {actual_hash}"))
            continue
        if not destination.exists():
            plan.items.append(ImportItem("copy", relative, source, destination))
            continue
        if sha256_file(destination) == actual_hash:
            plan.items.append(ImportItem("identical", relative, source, destination))
            continue
        conflict_path = conflict_root / relative
        plan.items.append(ImportItem("conflict", relative, source, destination, conflict_path=conflict_path))
    return plan


def apply_import(plan: ImportPlan) -> Dict[str, Any]:
    invalid = [item for item in plan.items if item.action in ("missing-source", "invalid-source-hash")]
    if invalid:
        raise ValueError(f"Import source verification failed for {len(invalid)} file(s)")
    copied = []
    conflicts = []
    for item in plan.items:
        if item.action == "copy":
            _copy_atomic(item.source, item.destination)
            copied.append(item.destination)
        elif item.action == "conflict" and item.conflict_path:
            _copy_atomic(item.source, item.conflict_path)
            conflicts.append(item.conflict_path)
    return {"copied": copied, "conflicts": conflicts, "counts": plan.counts}


def _sanitize_file(source: Path, destination: Path) -> Dict[str, Any]:
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
    changed = _write_if_changed(destination, encoded)
    return {
        "bytes": len(encoded), "sha256": digest, "changed": changed,
        "kept": kept, "omitted": omitted, "invalid": invalid,
        "media": media, "secrets": secrets,
    }


def _write_if_changed(destination: Path, content: bytes) -> bool:
    if destination.exists() and destination.read_bytes() == content:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".tmp")
    temp.write_bytes(content)
    temp.replace(destination)
    return True


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".incoming")
    shutil.copy2(source, temp)
    temp.replace(destination)


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


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
