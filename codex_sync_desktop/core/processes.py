from __future__ import annotations

import csv
import os
import re
import signal
import time
import platform
import subprocess
from dataclasses import dataclass
from io import StringIO
from typing import List

from .git_client import hidden_window_kwargs


@dataclass
class ProcessInfo:
    pid: int
    name: str


BLOCKED_NAMES = ("codex", "chatgpt", "codex++", "codex-plus")


def running_codex_processes(current_pid: int | None = None, *, strict: bool = False) -> List[ProcessInfo]:
    if platform.system() == "Windows":
        command = ["tasklist", "/FO", "CSV", "/NH"]
    else:
        command = ["ps", "-axo", "pid=,comm="]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
            **hidden_window_kwargs("win32" if platform.system() == "Windows" else None),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        if strict:
            raise RuntimeError("无法读取进程列表，请手动退出相关程序后重试。") from exc
        return []
    if strict and result.returncode:
        raise RuntimeError("无法读取进程列表，请手动退出相关程序后重试。")
    output = result.stdout if isinstance(result.stdout, str) else ""
    matches: List[ProcessInfo] = []
    if platform.system() == "Windows":
        for row in csv.reader(StringIO(output)):
            if len(row) < 2:
                continue
            name, pid_text = row[0], row[1]
            try:
                pid = int(pid_text)
            except (TypeError, ValueError):
                continue
            if _is_blocked(name) and pid != current_pid:
                matches.append(ProcessInfo(pid, name))
    else:
        for line in output.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            pid, name = int(parts[0]), parts[1]
            if pid != current_pid and _is_blocked(name):
                matches.append(ProcessInfo(pid, name))
    return matches


def _is_blocked(name: str) -> bool:
    """Only executables belonging to these apps, never arbitrary substring matches."""
    lowered = name.lower().replace("\\", "/")
    if "codex sync desktop" in lowered or "codex-sync-desktop" in lowered:
        return False
    if re.search(r"/(?:chatgpt|codex|codex\+\+|codex-plus)\.app/contents/", lowered):
        return True
    executable = lowered.rsplit("/", 1)[-1].removesuffix(".exe")
    return executable in BLOCKED_NAMES or any(
        executable.startswith(app + " helper") for app in BLOCKED_NAMES
    )


@dataclass
class TerminationReport:
    requested: int
    remaining: List[ProcessInfo]
    errors: List[str]


def terminate_related_processes(current_pid: int | None = None, grace_seconds: float = 3.0) -> TerminationReport:
    """Terminate only revalidated related PIDs; never kill the sync tool itself.

    Run off the UI thread. Recheck names before each signal to avoid signalling a
    PID reused by another executable. Remaining helpers are rescanned after quit.
    """
    own_pid = current_pid if current_pid is not None else os.getpid()
    targets = {p.pid: p for p in running_codex_processes(own_pid, strict=True) if p.pid > 1 and p.pid != own_pid}
    errors = []
    if not targets:
        return TerminationReport(0, [], [])

    def stop(proc, force=False):
        try:
            if platform.system() == "Windows":
                command = ["taskkill", "/PID", str(proc.pid)]
                if force:
                    command.append("/F")
                result = subprocess.run(command, capture_output=True, text=True, timeout=8,
                                        **hidden_window_kwargs("win32"))
                if result.returncode:
                    errors.append(f"PID {proc.pid}：退出请求未完成")
            else:
                os.kill(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"PID {proc.pid}：{exc}")

    live = {p.pid: p for p in running_codex_processes(own_pid, strict=True)}
    for pid, target in targets.items():
        if pid in live and live[pid].name == target.name:
            stop(target)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        remaining = running_codex_processes(own_pid, strict=True)
        if not remaining:
            return TerminationReport(len(targets), [], errors)
        time.sleep(0.15)
    # Include newly spawned related helpers, but revalidate each PID immediately.
    remaining = running_codex_processes(own_pid, strict=True)
    for proc in remaining:
        if proc.pid <= 1 or proc.pid == own_pid:
            continue
        live = {p.pid: p for p in running_codex_processes(own_pid, strict=True)}
        if proc.pid in live and live[proc.pid].name == proc.name:
            stop(proc, force=True)
    if remaining:
        time.sleep(0.2)
    return TerminationReport(len(targets), running_codex_processes(own_pid, strict=True), errors)
