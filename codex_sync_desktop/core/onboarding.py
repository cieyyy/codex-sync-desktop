from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .git_client import CommandResult, command_environment, github_auth_status, run


GITHUB_SIGNUP_URL = "https://github.com/signup"
GITHUB_DEVICE_URL = "https://github.com/login/device"
GIT_DOWNLOAD_URL = "https://git-scm.com/downloads"
GH_DOWNLOAD_URL = "https://cli.github.com/"
GH_LATEST_RELEASE_API = "https://api.github.com/repos/cli/cli/releases/latest"
GIT_WINDOWS_LATEST_RELEASE_API = "https://api.github.com/repos/git-for-windows/git/releases/latest"
MAX_TOOL_DOWNLOAD_BYTES = 200 * 1024 * 1024
COMMON_LOCAL_PROXY_PORTS = (7890, 7897, 7891, 10809, 1080)


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


@dataclass
class DependencyInstallResult:
    completed: bool
    message: str


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
    candidates = []
    if sys.platform == "win32":
        candidates.extend(_windows_proxy_candidates())
    elif sys.platform == "darwin":
        candidates.extend(_macos_proxy_candidates())
    proxies = urllib.request.getproxies()
    candidates.extend(str(proxies.get(key) or "").strip() for key in ("https", "http"))
    for value in candidates:
        normalized = _normalize_proxy_candidate(value)
        if normalized:
            return normalized
    for port in COMMON_LOCAL_PROXY_PORTS:
        if _local_proxy_port_open(port):
            return f"http://127.0.0.1:{port}"
    return ""


def check_github_connectivity(proxy_url: str = "", timeout: int = 12) -> ConnectivityResult:
    proxy = validate_proxy_url(proxy_url)
    handlers = _url_handlers(proxy)
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
        reason = str(getattr(exc, "reason", None) or str(exc))
        if "CERTIFICATE_VERIFY_FAILED" in reason:
            reason = "TLS 证书校验失败：代理返回的证书不受内置可信 CA 认可；请检查代理 HTTPS/证书设置，不要关闭证书校验"
        return ConnectivityResult(False, reason=reason, proxy_used=bool(proxy))


def _url_handlers(proxy: str) -> list[urllib.request.BaseHandler]:
    proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else urllib.request.ProxyHandler({})
    ca_file = _trusted_ca_file()
    tls_context = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
    return [proxy_handler, urllib.request.HTTPSHandler(context=tls_context)]


def _trusted_ca_file() -> str:
    try:
        import certifi
    except ImportError:
        return ""
    return certifi.where()


def _normalize_proxy_candidate(value: str) -> str:
    raw = str(value or "").strip().strip('"')
    if not raw:
        return ""
    if ";" in raw or "=" in raw:
        parts = {}
        for item in raw.split(";"):
            if "=" in item:
                key, candidate = item.split("=", 1)
                parts[key.strip().lower()] = candidate.strip()
        raw = parts.get("https") or parts.get("http") or ""
    if raw and "://" not in raw:
        raw = "http://" + raw
    try:
        return validate_proxy_url(raw)
    except ValueError:
        return ""


def _windows_proxy_candidates() -> list[str]:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "")
        return [server] if enabled and server else []
    except (ImportError, OSError, TypeError, ValueError):
        return []


def _macos_proxy_candidates() -> list[str]:
    try:
        result = subprocess.run(
            ["/usr/sbin/scutil", "--proxy"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    values = {
        key: value.strip()
        for key, value in re.findall(r"(?m)^\s*([A-Za-z]+)\s*:\s*(.+?)\s*$", result.stdout or "")
    }
    candidates = []
    for prefix in ("HTTPS", "HTTP"):
        if values.get(prefix + "Enable") != "1":
            continue
        host = values.get(prefix + "Proxy", "")
        port = values.get(prefix + "Port", "")
        if host and port:
            candidates.append(f"http://{host}:{port}")
    return candidates


def _local_proxy_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.08):
            return True
    except OSError:
        return False


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
    if sys.platform == "win32":
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


def launch_dependency_install(app_home: Path, proxy_url: str = "") -> DependencyInstallResult:
    proxy = validate_proxy_url(proxy_url)
    app_home.mkdir(parents=True, exist_ok=True)
    git_probe = run(["git", "--version"], timeout=10, proxy_url=proxy)
    gh_probe = run(["gh", "--version"], timeout=10, proxy_url=proxy)
    if git_probe.ok and gh_probe.ok:
        clear_tool_installer_cache(app_home)
        return DependencyInstallResult(True, "Git 和 GitHub CLI 已可用，无需安装。")
    if sys.platform == "win32":
        winget = shutil.which("winget", path=command_environment().get("PATH"))
        winget_failures: list[str] = []
        latest_status = {"git": git_probe.ok, "gh": gh_probe.ok}
        if winget and not git_probe.ok:
            install = run(
                [winget, "install", "--id", "Git.Git", "-e", "--force", "--accept-package-agreements", "--accept-source-agreements"],
                timeout=900,
                proxy_url=proxy,
            )
            if not install.ok:
                winget_failures.append(f"Git: {_probe_reason(install, 'winget 安装失败')}")
            verified = github_setup_status(proxy)
            latest_status = verified
            if verified.get("git") and verified.get("gh"):
                clear_tool_installer_cache(app_home)
                return DependencyInstallResult(True, "Git 和 GitHub CLI 已自动安装完成，可以继续登录。")
        if not bool(latest_status.get("gh")):
            gh_path = install_windows_portable_gh(app_home, proxy)
            gh_check = run([str(gh_path), "--version"], timeout=10, proxy_url=proxy)
            if not gh_check.ok:
                raise RuntimeError(f"GitHub CLI 便携版安装后无法启动：{_probe_reason(gh_check, '启动失败')}")
            latest_status["gh"] = True
            if bool(latest_status.get("git")):
                clear_tool_installer_cache(app_home)
                return DependencyInstallResult(True, "GitHub CLI 已在软件目录中自动安装完成，可以继续登录。")
        need_git = not bool(latest_status.get("git"))
        if not need_git:
            raise RuntimeError("必要工具安装状态异常，请重新检测后重试")
        git_installer = download_latest_windows_git_installer(app_home, proxy)
        script = write_windows_tool_install_script(app_home, git_installer, proxy)
        subprocess.Popen(["powershell.exe", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", str(script)])
        fallback_note = "；winget 未成功，已切换官方安装包" if winget_failures else ""
        return DependencyInstallResult(False, f"GitHub CLI 已自动准备完成；Git 官方安装程序已打开{fallback_note}。按系统提示授权，软件会自动检测安装结果。")
    if sys.platform == "darwin":
        actions = []
        if not git_probe.ok:
            subprocess.Popen(["/usr/bin/xcode-select", "--install"])
            actions.append("macOS 命令行工具安装器")
        if not gh_probe.ok:
            installer = download_latest_macos_gh_installer(app_home, proxy)
            subprocess.Popen(["/usr/bin/open", str(installer)])
            actions.append("GitHub CLI 官方安装器")
        return DependencyInstallResult(False, "、".join(actions) + "已打开。完成系统授权后软件会自动检测。")
    raise RuntimeError("当前系统暂不支持自动安装，请使用官方下载入口")


def download_latest_windows_git_installer(app_home: Path, proxy_url: str = "") -> Path:
    return download_verified_release_asset(
        GIT_WINDOWS_LATEST_RELEASE_API,
        select_windows_git_installer_asset,
        app_home / "downloads" / "Git-for-Windows-64-bit.exe",
        proxy_url,
    )


def install_windows_portable_gh(app_home: Path, proxy_url: str = "") -> Path:
    architecture = "arm64" if os.environ.get("PROCESSOR_ARCHITECTURE", "").lower() == "arm64" else "amd64"
    archive = download_verified_release_asset(
        GH_LATEST_RELEASE_API,
        lambda release: select_windows_gh_portable_asset(release, architecture),
        app_home / "downloads" / f"GitHub-CLI-windows-{architecture}.zip",
        proxy_url,
    )
    destination = app_home / "tools" / "bin" / "gh.exe"
    temporary = destination.with_suffix(".installing")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as package:
            matches = []
            for item in package.infolist():
                normalized = item.filename.replace("\\", "/").lower().lstrip("/")
                if not item.is_dir() and (normalized == "bin/gh.exe" or normalized.endswith("/bin/gh.exe")):
                    matches.append(item)
            if len(matches) != 1:
                raise RuntimeError("GitHub CLI 官方 ZIP 内未找到唯一的 gh.exe")
            executable = matches[0]
            if executable.file_size <= 0 or executable.file_size > MAX_TOOL_DOWNLOAD_BYTES:
                raise RuntimeError("GitHub CLI 可执行文件大小异常")
            with package.open(executable) as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        archive.unlink(missing_ok=True)
    return destination


def write_windows_tool_install_script(
    app_home: Path,
    git_installer: Path,
    proxy_url: str = "",
) -> Path:
    proxy = validate_proxy_url(proxy_url)
    script = app_home / "install-sync-tools.ps1"
    proxy_lines = ""
    if proxy:
        escaped_proxy = proxy.replace("'", "''")
        proxy_lines = f"$env:HTTP_PROXY='{escaped_proxy}'\n$env:HTTPS_PROXY='{escaped_proxy}'\n"
    lines = ["$ErrorActionPreference='Stop'", proxy_lines.rstrip()]
    escaped_git = str(git_installer).replace("'", "''")
    lines.extend(
        (
            f"$git=Start-Process -FilePath '{escaped_git}' -ArgumentList @('/VERYSILENT','/NORESTART','/NOCANCEL','/SP-') -Wait -PassThru",
            'if ($git.ExitCode -ne 0) { throw "Git 安装失败，退出码 $($git.ExitCode)" }',
            f"Remove-Item -LiteralPath '{escaped_git}' -Force -ErrorAction SilentlyContinue",
        )
    )
    lines.extend(
        (
            "Write-Host '必要工具安装完成。Codex Sync Desktop 会自动检测结果。' -ForegroundColor Green",
            "Read-Host '按回车关闭窗口'",
        )
    )
    script.write_text("\n".join(line for line in lines if line) + "\n", encoding="utf-8-sig")
    return script


def download_latest_macos_gh_installer(app_home: Path, proxy_url: str = "") -> Path:
    return download_verified_release_asset(
        GH_LATEST_RELEASE_API,
        select_macos_gh_installer_asset,
        app_home / "downloads" / "GitHub-CLI-macOS-universal.pkg",
        proxy_url,
    )


def download_verified_release_asset(
    release_api: str,
    selector: Callable[[dict[str, object]], dict[str, object]],
    target: Path,
    proxy_url: str = "",
) -> Path:
    proxy = validate_proxy_url(proxy_url)
    handlers = _url_handlers(proxy)
    opener = urllib.request.build_opener(*handlers)
    headers = {"User-Agent": "Codex-Sync-Desktop", "Accept": "application/vnd.github+json"}
    request = urllib.request.Request(release_api, headers=headers)
    with opener.open(request, timeout=30) as response:
        release = json.loads(response.read().decode("utf-8"))
    asset = selector(release)
    size = int(asset.get("size") or 0)
    if size <= 0 or size > MAX_TOOL_DOWNLOAD_BYTES:
        raise RuntimeError("官方安装包大小异常，已停止下载")
    digest = str(asset.get("digest") or "")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise RuntimeError("官方安装包没有可用的 SHA-256 校验值")
    expected_hash = digest.removeprefix("sha256:").lower()
    url = str(asset.get("browser_download_url") or "")
    target.parent.mkdir(parents=True, exist_ok=True)
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
                    raise RuntimeError("官方安装包超过安全大小限制")
                hasher.update(chunk)
                output.write(chunk)
        if received != size:
            raise RuntimeError(f"官方安装包下载不完整：应为 {size} 字节，实际 {received} 字节")
        if hasher.hexdigest().lower() != expected_hash:
            raise RuntimeError("官方安装包 SHA-256 校验失败，文件已拒绝使用")
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


def select_windows_gh_portable_asset(release: dict[str, object], architecture: str = "amd64") -> dict[str, object]:
    if architecture not in {"amd64", "arm64"}:
        raise ValueError("不支持的 Windows 架构")
    return _select_official_asset(
        release,
        lambda name: name.endswith(f"_windows_{architecture}.zip"),
        "https://github.com/cli/cli/releases/download/",
        f"GitHub CLI Windows {architecture} ZIP",
    )


def select_windows_git_installer_asset(release: dict[str, object]) -> dict[str, object]:
    return _select_official_asset(
        release,
        lambda name: name.startswith("Git-") and name.endswith("-64-bit.exe"),
        "https://github.com/git-for-windows/git/releases/download/",
        "Git for Windows 64-bit",
    )


def _select_official_asset(
    release: dict[str, object],
    name_matches: Callable[[str], bool],
    url_prefix: str,
    label: str,
) -> dict[str, object]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError(f"{label} 最新版本信息缺少安装资源")
    matches = [
        asset for asset in assets
        if isinstance(asset, dict) and name_matches(str(asset.get("name") or ""))
    ]
    if len(matches) != 1:
        raise RuntimeError(f"未找到唯一的 {label} 官方安装包")
    asset = matches[0]
    if not str(asset.get("browser_download_url") or "").startswith(url_prefix):
        raise RuntimeError(f"{label} 下载地址不是 GitHub 官方地址")
    return asset


def clear_tool_installer_cache(app_home: Path) -> int:
    downloads = app_home / "downloads"
    if not downloads.is_dir():
        return 0
    removed = 0
    for item in downloads.iterdir():
        if item.is_file() and item.name in {
            "Git-for-Windows-64-bit.exe",
            "GitHub-CLI-windows-amd64.msi",
            "GitHub-CLI-windows-amd64.zip",
            "GitHub-CLI-windows-arm64.zip",
            "GitHub-CLI-macOS-universal.pkg",
        }:
            item.unlink(missing_ok=True)
            removed += 1
    return removed


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
    lowered = detail.lower()
    if "winerror 2" in lowered or "system cannot find the file" in lowered or "系统找不到指定的文件" in detail:
        detail = f"{fallback}；未在 PATH、常用安装目录或 Windows 注册表中找到"
    return detail if len(detail) <= 160 else detail[:157] + "..."
