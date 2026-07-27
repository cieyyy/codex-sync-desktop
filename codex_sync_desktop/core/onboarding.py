from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .git_client import CommandResult, command_environment, github_auth_status, run


GITHUB_SIGNUP_URL = "https://github.com/signup"
GITHUB_DEVICE_URL = "https://github.com/login/device"
GIT_DOWNLOAD_URL = "https://git-scm.com/downloads"
GH_DOWNLOAD_URL = "https://cli.github.com/"
GH_LATEST_RELEASE_API = "https://api.github.com/repos/cli/cli/releases/latest"
MAX_TOOL_DOWNLOAD_BYTES = 100 * 1024 * 1024


@dataclass
class ConnectivityResult:
    ok: bool
    status: int = 0
    reason: str = ""
    proxy_used: bool = False


@dataclass
class RepositorySetupResult:
    owner: str
    name: str
    url: str
    local_path: Path


def validate_proxy_url(value: str) -> str:
    proxy = value.strip()
    if not proxy:
        return ""
    parsed = urllib.parse.urlparse(proxy)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not parsed.port:
        raise ValueError("代理地址格式应为 http://127.0.0.1:端口")
    if parsed.username or parsed.password:
        raise ValueError("为了避免明文保存密码，请使用不含账号密码的本机代理地址")
    return proxy


def detect_system_proxy() -> str:
    proxies = urllib.request.getproxies()
    for key in ("https", "http"):
        value = str(proxies.get(key) or "").strip()
        if value:
            try:
                return validate_proxy_url(value)
            except ValueError:
                continue
    return ""


def check_github_connectivity(proxy_url: str = "", timeout: int = 12) -> ConnectivityResult:
    proxy = validate_proxy_url(proxy_url)
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else [urllib.request.ProxyHandler({})]
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(
        "https://api.github.com/meta",
        headers={"User-Agent": "Codex-Sync-Desktop", "Accept": "application/vnd.github+json"},
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
        return ConnectivityResult(200 <= status < 400, status, proxy_used=bool(proxy))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        return ConnectivityResult(False, reason=str(reason), proxy_used=bool(proxy))


def github_setup_status(proxy_url: str = "") -> dict[str, object]:
    git_probe = run(["git", "--version"], timeout=10, proxy_url=proxy_url)
    gh_probe = run(["gh", "--version"], timeout=10, proxy_url=proxy_url)
    authenticated = github_auth_status(proxy_url).ok if gh_probe.ok else False
    return {
        "git": git_probe.ok,
        "gh": gh_probe.ok,
        "authenticated": authenticated,
        "git_reason": "" if git_probe.ok else _probe_reason(git_probe, "Git 未安装或无法启动"),
        "gh_reason": "" if gh_probe.ok else _probe_reason(gh_probe, "GitHub CLI 未安装或无法启动"),
    }


def launch_github_login(app_home: Path, proxy_url: str = "") -> Path | None:
    proxy = validate_proxy_url(proxy_url)
    gh_path = shutil.which("gh", path=command_environment().get("PATH"))
    gh_probe = run(["gh", "--version"], timeout=10, proxy_url=proxy)
    if not gh_path or not gh_probe.ok:
        detail = _probe_reason(gh_probe, "未找到 GitHub CLI")
        raise FileNotFoundError(f"GitHub CLI 未安装或已损坏：{detail}。请点击“自动安装/修复必要工具”")
    app_home.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        escaped_gh = gh_path.replace("'", "''")
        prefix = ""
        if proxy:
            escaped_proxy = proxy.replace("'", "''")
            prefix = f"$env:HTTP_PROXY='{escaped_proxy}'; $env:HTTPS_PROXY='{escaped_proxy}'; "
        command = (
            f"{prefix}& '{escaped_gh}' auth login --hostname github.com --git-protocol https --web; "
            f"if ($LASTEXITCODE -eq 0) {{ & '{escaped_gh}' auth setup-git; Write-Host '登录成功，可以关闭此窗口。' -ForegroundColor Green }}"
        )
        subprocess.Popen(["powershell.exe", "-NoExit", "-Command", command])
        return None
    if sys.platform == "darwin":
        script = app_home / "github-login.command"
        exports = ""
        if proxy:
            quoted = shlex.quote(proxy)
            exports = f"export HTTP_PROXY={quoted}\nexport HTTPS_PROXY={quoted}\n"
        content = (
            "#!/bin/sh\n"
            f"{exports}{shlex.quote(gh_path)} auth login --hostname github.com --git-protocol https --web\n"
            f"status=$?\nif [ $status -eq 0 ]; then {shlex.quote(gh_path)} auth setup-git; echo '登录成功，可以关闭此窗口。'; fi\n"
            "printf '按回车关闭...'; read answer\nexit $status\n"
        )
        script.write_text(content, encoding="utf-8")
        script.chmod(0o700)
        subprocess.Popen(["open", str(script)])
        return script
    subprocess.Popen([gh_path, "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web"], env=command_environment(proxy_url=proxy))
    return None


def launch_dependency_install(app_home: Path, proxy_url: str = "") -> Path | None:
    proxy = validate_proxy_url(proxy_url)
    app_home.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        winget = shutil.which("winget")
        if not winget:
            raise FileNotFoundError("未找到 Windows winget，请使用下方官方下载按钮安装 Git 和 GitHub CLI")
        prefix = ""
        if proxy:
            escaped = proxy.replace("'", "''")
            prefix = f"$env:HTTP_PROXY='{escaped}'; $env:HTTPS_PROXY='{escaped}'; "
        command = (
            f"{prefix}winget install --id Git.Git -e --force --accept-package-agreements --accept-source-agreements; "
            "winget install --id GitHub.cli -e --force --accept-package-agreements --accept-source-agreements; "
            "Write-Host '安装结束。请重新打开 Codex Sync Desktop 后继续。' -ForegroundColor Green"
        )
        subprocess.Popen(["powershell.exe", "-NoExit", "-Command", command])
        return None
    if sys.platform == "darwin":
        brew = shutil.which("brew", path=command_environment().get("PATH"))
        if not brew:
            git_probe = run(["git", "--version"], timeout=10, proxy_url=proxy)
            if not git_probe.ok:
                subprocess.Popen(["xcode-select", "--install"])
            installer = download_latest_macos_gh_installer(app_home, proxy)
            subprocess.Popen(["open", str(installer)])
            return installer
        script = app_home / "install-sync-tools.command"
        exports = ""
        if proxy:
            quoted = shlex.quote(proxy)
            exports = f"export HTTP_PROXY={quoted}\nexport HTTPS_PROXY={quoted}\n"
        script.write_text(
            "#!/bin/sh\n"
            f"{exports}{shlex.quote(brew)} install git gh\n"
            "status=$?\nprintf '安装结束，请重新打开 Codex Sync Desktop。按回车关闭...'; read answer\nexit $status\n",
            encoding="utf-8",
        )
        script.chmod(0o700)
        subprocess.Popen(["open", str(script)])
        return script
    raise RuntimeError("当前系统暂不支持自动安装，请使用官方下载入口")


def download_latest_macos_gh_installer(app_home: Path, proxy_url: str = "") -> Path:
    proxy = validate_proxy_url(proxy_url)
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else [urllib.request.ProxyHandler({})]
    opener = urllib.request.build_opener(*handlers)
    headers = {"User-Agent": "Codex-Sync-Desktop", "Accept": "application/vnd.github+json"}
    request = urllib.request.Request(GH_LATEST_RELEASE_API, headers=headers)
    with opener.open(request, timeout=30) as response:
        release = json.loads(response.read().decode("utf-8"))
    asset = select_macos_gh_installer_asset(release)
    size = int(asset.get("size") or 0)
    if size <= 0 or size > MAX_TOOL_DOWNLOAD_BYTES:
        raise RuntimeError("GitHub CLI 官方安装包大小异常，已停止下载")
    digest = str(asset.get("digest") or "")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise RuntimeError("GitHub CLI 官方安装包没有可用的 SHA-256 校验值")
    expected_hash = digest.removeprefix("sha256:").lower()
    url = str(asset.get("browser_download_url") or "")
    target_dir = app_home / "downloads"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "GitHub-CLI-macOS-universal.pkg"
    temporary = target.with_suffix(".download")
    download_request = urllib.request.Request(url, headers={"User-Agent": "Codex-Sync-Desktop"})
    hasher = hashlib.sha256()
    received = 0
    try:
        with opener.open(download_request, timeout=180) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_TOOL_DOWNLOAD_BYTES:
                    raise RuntimeError("GitHub CLI 官方安装包超过安全大小限制")
                hasher.update(chunk)
                output.write(chunk)
        if received != size:
            raise RuntimeError(f"GitHub CLI 安装包下载不完整：应为 {size} 字节，实际 {received} 字节")
        if hasher.hexdigest().lower() != expected_hash:
            raise RuntimeError("GitHub CLI 安装包 SHA-256 校验失败，文件已拒绝使用")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def select_macos_gh_installer_asset(release: dict[str, object]) -> dict[str, object]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("GitHub CLI 最新版本信息缺少安装资源")
    matches = [
        asset for asset in assets
        if isinstance(asset, dict) and str(asset.get("name") or "").endswith("_macOS_universal.pkg")
    ]
    if len(matches) != 1:
        raise RuntimeError("未找到唯一的 GitHub CLI macOS universal.pkg 官方安装包")
    asset = matches[0]
    url = str(asset.get("browser_download_url") or "")
    if not url.startswith("https://github.com/cli/cli/releases/download/"):
        raise RuntimeError("GitHub CLI 安装包下载地址不是 GitHub 官方地址")
    return asset


def create_private_repository(
    local_path: Path,
    repository_name: str,
    proxy_url: str = "",
) -> RepositorySetupResult:
    name = repository_name.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name):
        raise ValueError("仓库名称只能包含字母、数字、点、横线和下划线，最长 100 个字符")
    proxy = validate_proxy_url(proxy_url)
    git_probe = run(["git", "--version"], timeout=10, proxy_url=proxy)
    gh_probe = run(["gh", "--version"], timeout=10, proxy_url=proxy)
    if not git_probe.ok or not gh_probe.ok:
        missing = []
        if not git_probe.ok:
            missing.append(_probe_reason(git_probe, "Git 未安装或无法启动"))
        if not gh_probe.ok:
            missing.append(_probe_reason(gh_probe, "GitHub CLI 未安装或无法启动"))
        raise RuntimeError("必要工具不可用：" + "；".join(missing))
    auth = github_auth_status(proxy)
    if not auth.ok:
        raise RuntimeError("GitHub 尚未登录，请先点击“打开 GitHub 登录”")
    target = local_path.expanduser().resolve()
    if target.exists() and not target.is_dir():
        raise FileExistsError(f"本地同步路径不是目录：{target}")

    user_result = run(["gh", "api", "user"], timeout=30, proxy_url=proxy)
    _require_ok(user_result, "读取 GitHub 账号失败")
    user = json.loads(user_result.output)
    owner = str(user.get("login") or "").strip()
    user_id = str(user.get("id") or "").strip()
    if not owner or not user_id:
        raise RuntimeError("GitHub 账号信息不完整")
    full_name = f"{owner}/{name}"

    view = run(["gh", "repo", "view", full_name, "--json", "isPrivate,url,nameWithOwner"], timeout=30, proxy_url=proxy)
    if not view.ok:
        created = run(
            ["gh", "repo", "create", full_name, "--private", "--description", "Private Codex conversation sync vault"],
            timeout=60,
            proxy_url=proxy,
        )
        _require_ok(created, "创建 GitHub 私有仓库失败")

    verified = run(["gh", "repo", "view", full_name, "--json", "isPrivate,url,nameWithOwner"], timeout=30, proxy_url=proxy)
    _require_ok(verified, "验证 GitHub 仓库失败")
    repository = json.loads(verified.output)
    if repository.get("isPrivate") is not True:
        raise RuntimeError("安全检查失败：目标仓库不是私有仓库")
    url = str(repository.get("url") or f"https://github.com/{full_name}")
    remote = url.rstrip("/") + ".git"

    setup_git = run(["gh", "auth", "setup-git"], timeout=30, proxy_url=proxy)
    _require_ok(setup_git, "配置 GitHub 凭据失败")
    if (target / ".git").is_dir():
        current_remote = run(["git", "remote", "get-url", "origin"], target, timeout=20, proxy_url=proxy)
        _require_ok(current_remote, "读取本地仓库地址失败")
        expected_key = f"github.com/{full_name}".lower()
        actual_key = current_remote.output.strip().removesuffix(".git").replace(":", "/").lower()
        if expected_key not in actual_key:
            raise RuntimeError("本地目录已经连接到另一个 GitHub 仓库，请选择新的空目录")
    else:
        if target.exists() and any(target.iterdir()):
            raise FileExistsError(f"本地目录不是空目录：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        clone = run(["git", "clone", remote, str(target)], timeout=300, proxy_url=proxy)
        _require_ok(clone, "克隆私有仓库失败")
    _require_ok(run(["git", "config", "user.name", owner], target, proxy_url=proxy), "配置 Git 用户名失败")
    _require_ok(run(["git", "config", "user.email", f"{user_id}+{owner}@users.noreply.github.com"], target, proxy_url=proxy), "配置 Git 邮箱失败")
    return RepositorySetupResult(owner, name, url, target)


def _require_ok(result: CommandResult, label: str) -> None:
    if not result.ok:
        detail = result.output.strip().splitlines()[-1] if result.output.strip() else "未知错误"
        raise RuntimeError(f"{label}：{detail}")


def _probe_reason(result: CommandResult, fallback: str) -> str:
    detail = result.output.strip().splitlines()[-1] if result.output.strip() else fallback
    return detail if len(detail) <= 160 else detail[:157] + "..."
