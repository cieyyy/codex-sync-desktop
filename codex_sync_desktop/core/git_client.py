from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class CommandResult:
    ok: bool
    output: str
    returncode: int


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def run(command: Sequence[str], cwd: Path | None = None, timeout: int = 120) -> CommandResult:
    try:
        result = subprocess.run(
            list(command), cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(False, str(exc), 1)
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return CommandResult(result.returncode == 0, output, result.returncode)


def github_auth_status() -> CommandResult:
    if not command_available("gh"):
        return CommandResult(False, "GitHub CLI (gh) is not installed", 127)
    return run(["gh", "auth", "status"], timeout=20)


class VaultGit:
    def __init__(self, path: Path, remote: str = ""):
        self.path = path
        self.remote = remote

    def prepare(self) -> CommandResult:
        if (self.path / ".git").exists():
            return CommandResult(True, "Repository is ready", 0)
        if self.remote:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return run(["git", "clone", self.remote, str(self.path)], timeout=300)
        self.path.mkdir(parents=True, exist_ok=True)
        result = run(["git", "init", "-b", "main"], self.path)
        if result.ok:
            (self.path / "sessions-text" / "devices").mkdir(parents=True, exist_ok=True)
        return result

    def pull(self) -> CommandResult:
        return run(["git", "pull", "--rebase", "--autostash"], self.path, timeout=300)

    def status(self) -> CommandResult:
        return run(["git", "status", "--short", "--branch"], self.path)

    def commit_and_push(self, message: str) -> CommandResult:
        add = run(["git", "add", "--all"], self.path)
        if not add.ok:
            return add
        staged = run(["git", "diff", "--cached", "--quiet"], self.path)
        if staged.returncode == 0:
            return CommandResult(True, "No changes to push", 0)
        commit = run(["git", "commit", "-m", message], self.path)
        if not commit.ok:
            return commit
        return run(["git", "push"], self.path, timeout=300)
