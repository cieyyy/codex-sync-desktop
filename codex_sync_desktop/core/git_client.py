from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


MACOS_COMMAND_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
)


@dataclass
class CommandResult:
    ok: bool
    output: str
    returncode: int


def summarize_pull(output: str) -> str:
    match = re.search(r"(?m)^\s*(\d+)\s+files? changed(?:,.*)?$", output)
    if match:
        count = int(match.group(1))
    elif "Already up to date." in output or "Already up-to-date." in output:
        count = 0
    else:
        count = len(re.findall(r"(?m)^\s*.+\|\s+\d+\s+[+\-]+\s*$", output))
    if "Fast-forward" in output:
        status = "Fast-forward"
    elif "Successfully rebased" in output:
        status = "Rebase 完成"
    elif count == 0:
        status = "已经是最新"
    else:
        status = "同步完成"
    return f"结果：成功\n数量：{count} 个文件\n状态：{status}"


def compact_failure_reason(output: str, fallback: str = "Git 命令执行失败") -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    markers = ("fatal:", "error:", "failed", "denied", "authentication", "could not", "conflict")
    reason = next(
        (line for line in reversed(lines) if any(marker in line.lower() for marker in markers)),
        lines[-1] if lines else fallback,
    )
    return reason if len(reason) <= 300 else reason[:297] + "..."


def command_environment(
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    entries = [item for item in env.get("PATH", "").split(os.pathsep) if item]
    if (platform_name or sys.platform) == "darwin":
        entries = [*MACOS_COMMAND_PATHS, *entries]
    env["PATH"] = os.pathsep.join(dict.fromkeys(entries))
    return env


def command_available(name: str) -> bool:
    env = command_environment()
    return shutil.which(name, path=env.get("PATH")) is not None


def run(command: Sequence[str], cwd: Path | None = None, timeout: int = 120) -> CommandResult:
    try:
        result = subprocess.run(
            list(command), cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, timeout=timeout, check=False, env=command_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(False, str(exc), 1)
    output_parts = []
    for part in (result.stdout, result.stderr):
        if not isinstance(part, str):
            continue
        normalized = part.strip()
        if normalized:
            output_parts.append(normalized)
    output = "\n".join(output_parts)
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
