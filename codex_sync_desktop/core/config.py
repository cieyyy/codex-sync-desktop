from __future__ import annotations

import json
import os
import platform
import re
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict


APP_DIR_NAME = "codex-sync-desktop"


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def default_app_home() -> Path:
    if platform.system() == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif platform.system() == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / APP_DIR_NAME


def device_slug(name: str | None = None) -> str:
    value = (name or socket.gethostname()).strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value).strip("-.")
    return value or "device"


@dataclass
class Settings:
    codex_home: str = field(default_factory=lambda: str(default_codex_home()))
    vault_path: str = ""
    vault_remote: str = ""
    device_name: str = field(default_factory=socket.gethostname)
    path_mappings: Dict[str, str] = field(default_factory=dict)
    auto_pull_before_import: bool = True
    auto_push_after_export: bool = True
    proxy_url: str = ""
    china_network_mode: bool = False
    onboarding_complete: bool = False

    @property
    def codex_path(self) -> Path:
        return Path(self.codex_home).expanduser().resolve()

    @property
    def vault(self) -> Path | None:
        return Path(self.vault_path).expanduser().resolve() if self.vault_path else None


class SettingsStore:
    def __init__(self, app_home: Path | None = None):
        self.app_home = app_home or default_app_home()
        self.path = self.app_home / "config.json"

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Settings()
        # Settings written before the guided onboarding existed already had a
        # working vault. Treat those installations as migrated so an upgrade
        # does not unexpectedly reopen the first-run wizard. New interrupted
        # onboarding writes the explicit false value and remains resumable.
        if "onboarding_complete" not in data and data.get("vault_path"):
            data["onboarding_complete"] = True
        allowed = Settings.__dataclass_fields__.keys()
        return Settings(**{key: value for key, value in data.items() if key in allowed})

    def save(self, settings: Settings) -> None:
        self.app_home.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.path)
