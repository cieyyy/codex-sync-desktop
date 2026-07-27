from __future__ import annotations

import csv
import platform
import subprocess
from dataclasses import dataclass
from io import StringIO
from typing import List


@dataclass
class ProcessInfo:
    pid: int
    name: str


BLOCKED_NAMES = ("codex", "chatgpt", "codex++", "codex-plus")


def running_codex_processes(current_pid: int | None = None) -> List[ProcessInfo]:
    if platform.system() == "Windows":
        command = ["tasklist", "/FO", "CSV", "/NH"]
    else:
        command = ["ps", "-axo", "pid=,comm="]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return []
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
    lowered = name.lower().replace(".exe", "")
    return any(token in lowered for token in BLOCKED_NAMES)
