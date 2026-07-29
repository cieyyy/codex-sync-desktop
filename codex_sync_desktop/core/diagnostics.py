from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Dict

from .backups import find_state_databases
from .git_client import command_available, github_auth_status, run
from .processes import running_codex_processes
from .sessions import iter_session_files


def platform_description() -> str:
    if sys.platform == "win32" and hasattr(sys, "getwindowsversion"):
        version = sys.getwindowsversion()
        return f"Windows-{version.major}.{version.minor}.{version.build}"
    try:
        return platform.platform()
    except (AttributeError, OSError):
        return sys.platform


def vault_uses_lfs(vault: Path | None) -> bool:
    if not vault or not vault.exists():
        return False
    try:
        attributes = (
            path for path in vault.rglob(".gitattributes")
            if ".git" not in path.relative_to(vault).parts
        )
        return any("filter=lfs" in path.read_text(encoding="utf-8", errors="replace") for path in attributes)
    except OSError:
        return False


def session_index_summary(diagnostics: Dict[str, Any]) -> tuple[str, str]:
    if diagnostics.get("session_index"):
        return "正常", "session_index.jsonl"
    if int(diagnostics.get("sessions") or 0) == 0:
        return "待生成（正常）", "当前没有本地会话，无需创建侧栏索引；首次导入时会自动生成"
    return "缺失", "本地已有会话；请执行“导入并修复”，或使用 Codex++ 修复"


def remediation_text(diagnostics: Dict[str, Any]) -> str:
    windows = str(diagnostics.get("platform", "")).startswith("Windows")
    git_install = (
        "winget install --id Git.Git -e --source winget"
        if windows else "brew install git"
    )
    lfs_install = (
        "winget install --id GitHub.GitLFS -e --source winget\ngit lfs install"
        if windows else "brew install git-lfs\ngit lfs install"
    )
    gh_install = (
        "winget install --id GitHub.cli -e --source winget\ngh auth login"
        if windows else "brew install gh\ngh auth login"
    )
    sections = ["Codex Sync Desktop 环境解决办法", ""]
    required = []
    optional = []
    if not diagnostics.get("codex_home_exists"):
        required.append("Codex 数据目录：打开“设置”，将目录指向当前用户的 .codex 文件夹。")
    if not diagnostics.get("databases"):
        required.append("状态数据库：先启动一次 Codex；如果仍缺失，检查设置中的 Codex 数据目录。")
    if not diagnostics.get("session_index") and int(diagnostics.get("sessions") or 0) > 0:
        required.append("侧栏索引：完成会话导入后执行“导入并修复归档”，或使用 Codex++ 修复历史会话。")
    if not diagnostics.get("git"):
        required.append(f"Git（同步必需）：\n{git_install}")
    if not diagnostics.get("vault_exists"):
        required.append("同步仓库：打开“设置”，选择本地仓库；没有本地仓库时填写远程地址后初始化/克隆。")
    if not diagnostics.get("git_lfs"):
        label = "Git LFS（当前仓库必需）" if diagnostics.get("git_lfs_required") else "Git LFS（当前仓库未使用，可选）"
        item = f"{label}：\n{lfs_install}"
        (required if diagnostics.get("git_lfs_required") else optional).append(item)
    if not diagnostics.get("gh"):
        item = f"GitHub CLI（首次自动创建私有仓库必需）：\n{gh_install}"
        (required if not diagnostics.get("vault_exists") else optional).append(item)
    elif not diagnostics.get("gh_authenticated"):
        item = "GitHub 登录（首次自动配置必需）：\ngh auth login\n也可以回到软件点击“首次配置向导”。"
        (required if not diagnostics.get("vault_exists") else optional).append(item)

    sections.append("必须处理" if required else "必须处理：无")
    for index, item in enumerate(required, 1):
        sections.extend((f"{index}. {item}", ""))
    if optional:
        sections.append("可选项")
        for index, item in enumerate(optional, 1):
            sections.extend((f"{index}. {item}", ""))
    if not windows:
        sections.extend(("macOS 如果提示 brew: command not found，请先访问 https://brew.sh 安装 Homebrew。", ""))
    sections.extend(("中国大陆或受限网络：先启动符合所在地法律和组织规定的代理工具，再在“首次配置向导”中填写本机 HTTP 代理并测试。", ""))
    sections.append("完成后关闭并重新打开本工具，再点击“刷新检查”。")
    return "\n".join(sections).strip() + "\n"


def collect_diagnostics(codex_home: Path, vault: Path | None = None, proxy_url: str = "") -> Dict[str, Any]:
    processes = running_codex_processes(os.getpid())
    sessions = sum(1 for _ in iter_session_files(codex_home)) if codex_home.exists() else 0
    databases = find_state_databases(codex_home) if codex_home.exists() else []
    gh_status = github_auth_status(proxy_url)
    result: Dict[str, Any] = {
        "platform": platform_description(),
        "codex_home": str(codex_home),
        "codex_home_exists": codex_home.exists(),
        "sessions": sessions,
        "databases": [str(path) for path in databases],
        "session_index": (codex_home / "session_index.jsonl").exists(),
        "session_index_required": sessions > 0,
        "git": command_available("git"),
        "git_lfs": command_available("git-lfs"),
        "git_lfs_required": vault_uses_lfs(vault),
        "gh": command_available("gh"),
        "gh_authenticated": gh_status.ok,
        "running_processes": [{"pid": item.pid, "name": item.name} for item in processes],
    }
    if vault:
        result["vault"] = str(vault)
        result["vault_exists"] = vault.exists()
        if (vault / ".git").exists():
            status = run(["git", "status", "--short", "--branch"], vault, proxy_url=proxy_url)
            result["vault_git_status"] = status.output
    return result


def diagnostics_json(codex_home: Path, vault: Path | None = None, proxy_url: str = "") -> str:
    return json.dumps(collect_diagnostics(codex_home, vault, proxy_url), ensure_ascii=False, indent=2)
