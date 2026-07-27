from __future__ import annotations

import json
import hashlib
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import ImportPlan


INDEX_FILES = ("session_index.jsonl", ".codex-global-state.json")
BACKUP_ROOT_NAMES = ("sync-backups", "import-backups", "import-conflicts")


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def find_state_databases(codex_home: Path) -> list[Path]:
    candidates = list(codex_home.glob("state_*.sqlite"))
    candidates.extend((codex_home / "sqlite").glob("*.db") if (codex_home / "sqlite").exists() else [])
    return sorted(path for path in candidates if path.is_file())


def create_consistent_backup(codex_home: Path, backup_root: Path | None = None) -> Path:
    root = backup_root or codex_home / "sync-backups" / timestamp_slug()
    root.mkdir(parents=True, exist_ok=False)
    copied = []
    for source in find_state_databases(codex_home):
        relative = source.relative_to(codex_home)
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(source))) as source_db, closing(sqlite3.connect(str(destination))) as destination_db:
            source_db.backup(destination_db)
        copied.append(relative.as_posix())
    for name in INDEX_FILES:
        source = codex_home / name
        if source.exists():
            shutil.copy2(source, root / name)
            copied.append(name)
    (root / "backup.json").write_text(
        json.dumps({"created_at": datetime.now(timezone.utc).isoformat(), "files": copied}, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def restore_backup(codex_home: Path, backup_dir: Path, names: Iterable[str] | None = None) -> list[Path]:
    metadata = backup_dir / "backup.json"
    if not metadata.exists():
        raise ValueError("Selected directory is not a Codex Sync backup")
    allowed = set(names or json.loads(metadata.read_text(encoding="utf-8")).get("files", []))
    restored = []
    for name in allowed:
        relative = Path(str(name))
        if relative.is_absolute() or ".." in relative.parts:
            continue
        source = backup_dir / relative
        if not source.is_file():
            continue
        destination = codex_home / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        restored.append(destination)
    return restored


def create_import_transaction(codex_home: Path, plan: ImportPlan) -> Path:
    root = codex_home / "sync-backups" / timestamp_slug()
    create_consistent_backup(codex_home, root)
    copied = []
    merged = []
    for item in plan.items:
        if item.action not in ("copy", "conflict"):
            continue
        destination = _relative_to_home(codex_home, item.destination)
        if item.action == "copy":
            copied.append({
                "path": destination.as_posix(),
                "after_sha256": _sha256_file(item.source),
            })
            continue
        if item.merged_content is None or not item.destination.is_file():
            raise ValueError(f"Cannot back up merge target: {item.destination}")
        backup_relative = Path("sessions-before") / destination
        backup_path = root / backup_relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.destination, backup_path)
        merged.append({
            "path": destination.as_posix(),
            "backup": backup_relative.as_posix(),
            "after_sha256": hashlib.sha256(item.merged_content).hexdigest(),
        })
    transaction = {
        "format": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_device": plan.source_device,
        "status": "prepared",
        "copied": copied,
        "merged": merged,
    }
    _write_json_atomic(root / "transaction.json", transaction)
    return root


def finish_import_transaction(transaction_dir: Path, counts: dict[str, int], status: str = "completed") -> None:
    path = transaction_dir / "transaction.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = status
    data["finished_at"] = datetime.now(timezone.utc).isoformat()
    data["counts"] = counts
    _write_json_atomic(path, data)


def rollback_import_transaction(codex_home: Path, transaction_dir: Path) -> dict[str, int]:
    transaction_path = transaction_dir / "transaction.json"
    if not transaction_path.is_file():
        raise ValueError("Selected backup is not an import transaction")
    data = json.loads(transaction_path.read_text(encoding="utf-8"))
    if data.get("status") == "rolled_back":
        raise ValueError("This import has already been rolled back")
    copied = list(data.get("copied") or [])
    merged = list(data.get("merged") or [])

    changes = []
    for entry in (*copied, *merged):
        relative = _safe_relative(str(entry.get("path", "")))
        destination = codex_home / relative
        expected = str(entry.get("after_sha256") or "")
        if not destination.is_file():
            raise FileNotFoundError(f"Imported session is missing: {destination}")
        actual = _sha256_file(destination)
        if expected and actual != expected:
            changes.append(relative.as_posix())
    if changes:
        preview = ", ".join(changes[:3])
        raise RuntimeError(f"{len(changes)} session(s) changed after import; refusing rollback: {preview}")

    for entry in merged:
        backup = transaction_dir / _safe_relative(str(entry.get("backup", "")))
        if not backup.is_file():
            raise FileNotFoundError(f"Session backup is missing: {backup}")

    removed = 0
    restored_sessions = 0
    for entry in copied:
        destination = codex_home / _safe_relative(str(entry["path"]))
        destination.unlink()
        removed += 1
    for entry in merged:
        destination = codex_home / _safe_relative(str(entry["path"]))
        backup = transaction_dir / _safe_relative(str(entry["backup"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, destination)
        restored_sessions += 1

    restored_state = restore_backup(codex_home, transaction_dir)
    backup_meta = json.loads((transaction_dir / "backup.json").read_text(encoding="utf-8"))
    backed_up = set(str(item) for item in backup_meta.get("files", []))
    for name in INDEX_FILES:
        current = codex_home / name
        if name not in backed_up and current.is_file():
            current.unlink()

    data["status"] = "rolled_back"
    data["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(transaction_path, data)
    return {"removed": removed, "restored_sessions": restored_sessions, "restored_state": len(restored_state)}


def list_backup_records(codex_home: Path) -> list[dict[str, Any]]:
    root = codex_home / "sync-backups"
    if not root.is_dir():
        return []
    records = []
    for directory in sorted((item for item in root.iterdir() if item.is_dir()), reverse=True):
        transaction_path = directory / "transaction.json"
        try:
            transaction = json.loads(transaction_path.read_text(encoding="utf-8")) if transaction_path.is_file() else {}
        except (OSError, ValueError):
            transaction = {"status": "invalid"}
        files = [item for item in directory.rglob("*") if item.is_file()]
        records.append({
            "path": directory,
            "created": directory.name,
            "kind": "完整导入" if transaction_path.is_file() else "索引快照",
            "status": transaction.get("status", "available"),
            "files": len(files),
            "bytes": sum(item.stat().st_size for item in files),
            "copied": len(transaction.get("copied") or []),
            "merged": len(transaction.get("merged") or []),
        })
    return records


def latest_reversible_transaction(codex_home: Path) -> Path | None:
    for record in list_backup_records(codex_home):
        if record["kind"] == "完整导入" and record["status"] in ("prepared", "completed", "failed"):
            return record["path"]
    return None


def prune_backup_history(codex_home: Path, keep: int = 1) -> int:
    root = codex_home / "sync-backups"
    if not root.is_dir():
        return 0
    directories = sorted((item for item in root.iterdir() if item.is_dir()), reverse=True)
    removed = 0
    for directory in directories[max(0, keep):]:
        shutil.rmtree(directory)
        removed += 1
    return removed


def clear_backup_storage(codex_home: Path) -> dict[str, int]:
    files = 0
    bytes_removed = 0
    roots = 0
    home = codex_home.resolve()
    for name in BACKUP_ROOT_NAMES:
        root = (codex_home / name).resolve()
        if root.parent != home or root.name != name:
            raise ValueError(f"Unsafe backup root: {root}")
        if not root.exists():
            continue
        entries = [item for item in root.rglob("*") if item.is_file()]
        files += len(entries)
        bytes_removed += sum(item.stat().st_size for item in entries)
        shutil.rmtree(root)
        roots += 1
    return {"roots": roots, "files": files, "bytes": bytes_removed}


def _relative_to_home(codex_home: Path, path: Path) -> Path:
    try:
        return path.resolve().relative_to(codex_home.resolve())
    except ValueError as exc:
        raise ValueError(f"Path is outside Codex home: {path}") from exc


def _safe_relative(value: str) -> Path:
    relative = Path(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe relative path: {value}")
    return relative


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
