from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any, Dict

from .backups import find_state_databases
from .git_client import command_available, github_auth_status, run
from .processes import running_codex_processes
from .sessions import iter_session_files


def collect_diagnostics(codex_home: Path, vault: Path | None = None) -> Dict[str, Any]:
    processes = running_codex_processes()
    sessions = sum(1 for _ in iter_session_files(codex_home)) if codex_home.exists() else 0
    databases = find_state_databases(codex_home) if codex_home.exists() else []
    gh_status = github_auth_status()
    result: Dict[str, Any] = {
        "platform": platform.platform(),
        "codex_home": str(codex_home),
        "codex_home_exists": codex_home.exists(),
        "sessions": sessions,
        "databases": [str(path) for path in databases],
        "session_index": (codex_home / "session_index.jsonl").exists(),
        "git": command_available("git"),
        "git_lfs": command_available("git-lfs"),
        "gh": command_available("gh"),
        "gh_authenticated": gh_status.ok,
        "running_processes": [{"pid": item.pid, "name": item.name} for item in processes],
    }
    if vault:
        result["vault"] = str(vault)
        result["vault_exists"] = vault.exists()
        if (vault / ".git").exists():
            status = run(["git", "status", "--short", "--branch"], vault)
            result["vault_git_status"] = status.output
    return result


def diagnostics_json(codex_home: Path, vault: Path | None = None) -> str:
    return json.dumps(collect_diagnostics(codex_home, vault), ensure_ascii=False, indent=2)
