from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


INDEX_FILES = ("session_index.jsonl", ".codex-global-state.json")


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
        destination = root / source.name
        with sqlite3.connect(str(source)) as source_db, sqlite3.connect(str(destination)) as destination_db:
            source_db.backup(destination_db)
        copied.append(source.name)
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
        source = backup_dir / name
        if not source.is_file() or Path(name).name != name:
            continue
        destination = codex_home / name
        shutil.copy2(source, destination)
        restored.append(destination)
    return restored
