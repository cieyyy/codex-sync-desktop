from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Mapping, Sequence


MACOS_COMMAND_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
)


def windows_command_paths(environ: Mapping[str, str]) -> tuple[str, ...]:
    program_files = environ.get("ProgramFiles", r"C:\Program Files")
    local_app_data = environ.get("LOCALAPPDATA", "")
    candidates = [
        str(PureWindowsPath(program_files) / "Git" / "cmd"),
        str(PureWindowsPath(program_files) / "GitHub CLI"),
    ]
    if local_app_data:
        candidates.extend(
            (
                str(PureWindowsPath(local_app_data) / "codex-sync-desktop" / "tools" / "bin"),
                str(PureWindowsPath(local_app_data) / "Programs" / "Git" / "cmd"),
                str(PureWindowsPath(local_app_data) / "Programs" / "GitHub CLI"),
                str(PureWindowsPath(local_app_data) / "Microsoft" / "WinGet" / "Links"),
            )
        )
    return tuple(candidates)


def windows_registry_command_paths() -> tuple[str, ...]:
    if sys.platform != "win32":
        return ()
    try:
        import winreg
    except ImportError:
        return ()

    candidates: list[str] = []
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    views = tuple(dict.fromkeys((
        getattr(winreg, "KEY_WOW64_64KEY", 0),
        getattr(winreg, "KEY_WOW64_32KEY", 0),
    )))

    def read_value(root: int, key_path: str, value_name: str | None, view: int) -> str:
        try:
            with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | view) as key:
                value, _kind = winreg.QueryValueEx(key, value_name)
        except OSError:
            return ""
        return str(value).strip().strip('"')

    for root in roots:
        for view in views:
            install_path = read_value(root, r"SOFTWARE\GitForWindows", "InstallPath", view)
            if install_path:
                candidates.extend(
                    (
                        str(PureWindowsPath(install_path) / "cmd"),
                        str(PureWindowsPath(install_path) / "bin"),
                    )
                )
            for executable in ("git.exe", "gh.exe"):
                executable_path = read_value(
                    root,
                    rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable}",
                    None,
                    view,
                )
                if executable_path:
                    candidates.append(str(PureWindowsPath(executable_path).parent))
    return tuple(dict.fromkeys(candidates))

TRANSIENT_PUSH_MARKERS = (
    "remote end hung up unexpectedly",
    "rpc failed",
    "http/2 stream",
    "unexpected disconnect",
    "connection reset",
    "connection was reset",
    "operation timed out",
    "network is unreachable",
)


def hidden_window_kwargs(platform_name: str | None = None) -> dict[str, object]:
    """Return subprocess options that prevent console flashes on Windows."""
    selected_platform = platform_name or sys.platform
    if selected_platform != "win32":
        return {}
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is None:
        return {"creationflags": creationflags}
    startupinfo = startupinfo_type()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return {"creationflags": creationflags, "startupinfo": startupinfo}


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
    lowered = output.lower()
    if "non-fast-forward" in lowered or "fetch first" in lowered:
        return "远端已有新提交，请先拉取仓库后重试。"
    if "authentication failed" in lowered or "permission denied" in lowered:
        return "GitHub 身份认证失败，请重新登录或检查仓库权限。"
    if is_transient_push_failure(output):
        return "连接在上传时中断；软件已自动使用 HTTP/1.1 重试，但仍未成功，请检查网络后重试。"
    markers = ("fatal:", "error:", "failed", "denied", "authentication", "could not", "conflict")
    reason = next(
        (line for line in reversed(lines) if any(marker in line.lower() for marker in markers)),
        lines[-1] if lines else fallback,
    )
    return reason if len(reason) <= 300 else reason[:297] + "..."


def is_transient_push_failure(output: str) -> bool:
    lowered = output.lower()
    return any(marker in lowered for marker in TRANSIENT_PUSH_MARKERS)


def is_missing_upstream(output: str) -> bool:
    lowered = output.lower()
    return (
        "has no upstream branch" in lowered
        or "set the remote as upstream" in lowered
        or "no tracking information for the current branch" in lowered
        or "set-upstream-to=origin/<branch>" in lowered
    )


def is_missing_remote_branch(output: str) -> bool:
    lowered = output.lower()
    return (
        "couldn't find remote ref" in lowered
        or "no such ref was fetched" in lowered
        or "remote repository is empty" in lowered
    )


def command_environment(
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    proxy_url: str = "",
) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    selected_platform = platform_name or sys.platform
    path_separator = ";" if selected_platform == "win32" else os.pathsep
    entries = [item for item in env.get("PATH", "").split(path_separator) if item]
    if selected_platform == "darwin":
        entries = [*MACOS_COMMAND_PATHS, *entries]
    elif selected_platform == "win32":
        entries = [*windows_registry_command_paths(), *windows_command_paths(env), *entries]
    env["PATH"] = path_separator.join(dict.fromkeys(entries))
    if proxy_url:
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
        env["http_proxy"] = proxy_url
        env["https_proxy"] = proxy_url
    return env


def command_available(name: str) -> bool:
    env = command_environment()
    return shutil.which(name, path=env.get("PATH")) is not None


def run(command: Sequence[str], cwd: Path | None = None, timeout: int = 120, proxy_url: str = "") -> CommandResult:
    try:
        result = subprocess.run(
            list(command), cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, timeout=timeout, check=False, env=command_environment(proxy_url=proxy_url),
            **hidden_window_kwargs(),
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


def github_auth_status(proxy_url: str = "") -> CommandResult:
    if not command_available("gh"):
        return CommandResult(False, "GitHub CLI (gh) is not installed", 127)
    return run(["gh", "auth", "status"], timeout=20, proxy_url=proxy_url)


class VaultGit:
    def __init__(self, path: Path, remote: str = "", proxy_url: str = ""):
        self.path = path
        self.remote = remote
        self.proxy_url = proxy_url

    def prepare(self) -> CommandResult:
        if (self.path / ".git").exists():
            return CommandResult(True, "Repository is ready", 0)
        if self.remote:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return run(["git", "clone", self.remote, str(self.path)], timeout=300, proxy_url=self.proxy_url)
        self.path.mkdir(parents=True, exist_ok=True)
        result = run(["git", "init", "-b", "main"], self.path, proxy_url=self.proxy_url)
        if result.ok:
            (self.path / "sessions-text" / "devices").mkdir(parents=True, exist_ok=True)
        return result

    def pull(self) -> CommandResult:
        result = run(["git", "pull", "--rebase", "--autostash"], self.path, timeout=300, proxy_url=self.proxy_url)
        if result.ok:
            return result
        if is_missing_remote_branch(result.output):
            return CommandResult(True, "Remote repository is empty", 0)
        if not is_missing_upstream(result.output):
            return result

        branch = run(["git", "branch", "--show-current"], self.path, proxy_url=self.proxy_url)
        branch_name = branch.output.strip()
        if not branch.ok or not branch_name:
            return branch if not branch.ok else result

        fetched = run(["git", "fetch", "origin", branch_name], self.path, timeout=300, proxy_url=self.proxy_url)
        if not fetched.ok:
            if is_missing_remote_branch(fetched.output):
                return CommandResult(True, "Remote repository is empty", 0)
            return fetched

        tracked = run(
            ["git", "branch", "--set-upstream-to", f"origin/{branch_name}", branch_name],
            self.path,
            proxy_url=self.proxy_url,
        )
        if not tracked.ok:
            return tracked
        return run(["git", "pull", "--rebase", "--autostash"], self.path, timeout=300, proxy_url=self.proxy_url)

    def status(self) -> CommandResult:
        return run(["git", "status", "--short", "--branch"], self.path, proxy_url=self.proxy_url)

    def commit_and_push(self, message: str) -> CommandResult:
        add = run(["git", "add", "--all"], self.path, proxy_url=self.proxy_url)
        if not add.ok:
            return add
        staged = run(["git", "diff", "--cached", "--quiet"], self.path, proxy_url=self.proxy_url)
        if staged.returncode not in (0, 1):
            return staged
        if staged.returncode == 1:
            commit = run(["git", "commit", "-m", message], self.path, proxy_url=self.proxy_url)
            if not commit.ok:
                return commit

        # Always push: a previous network failure may have left a clean working
        # tree with one or more local commits still ahead of the remote.
        push = run(["git", "push"], self.path, timeout=600, proxy_url=self.proxy_url)
        if not push.ok and is_missing_upstream(push.output):
            push = run(["git", "push", "--set-upstream", "origin", "HEAD"], self.path, timeout=600, proxy_url=self.proxy_url)
        if push.ok or not is_transient_push_failure(push.output):
            return push

        retry = run(["git", "-c", "http.version=HTTP/1.1", "push"], self.path, timeout=600, proxy_url=self.proxy_url)
        if retry.ok:
            return retry
        combined = "\n".join(part for part in (push.output, "HTTP/1.1 retry:", retry.output) if part)
        return CommandResult(False, combined, retry.returncode)
