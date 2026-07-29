from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SessionInfo:
    session_id: str
    path: Path
    relative_path: str
    created_at: int
    updated_at: int
    cwd: str
    title: str
    preview: str
    source: str = "app"
    model_provider: str = "openai"
    cli_version: str = ""
    archived: bool = False


@dataclass
class ExportReport:
    device: str
    sessions: int = 0
    changed_files: int = 0
    source_bytes: int = 0
    output_bytes: int = 0
    kept_lines: int = 0
    omitted_lines: int = 0
    invalid_lines: int = 0
    media_removed: int = 0
    secrets_redacted: int = 0
    removed_files: int = 0
    output: Optional[Path] = None


@dataclass
class ImportItem:
    action: str
    relative_path: str
    source: Path
    destination: Path
    merged_content: Optional[bytes] = None
    detail: str = ""
    task_id: str = ""
    source_title: str = ""
    local_title: str = ""


@dataclass
class ImportPlan:
    source_device: str
    items: List[ImportItem] = field(default_factory=list)
    title_updates: Dict[str, str] = field(default_factory=dict)

    @property
    def counts(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for item in self.items:
            result[item.action] = result.get(item.action, 0) + 1
        return result


@dataclass
class RepairReport:
    scanned: int = 0
    inserted: int = 0
    updated: int = 0
    index_entries: int = 0
    skipped: int = 0
    backup_dir: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)
