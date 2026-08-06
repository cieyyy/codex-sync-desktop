from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 packaging fallback
    tomllib = None  # type: ignore[assignment]


BUILTIN_MODEL_PROVIDERS = {"openai", "ollama", "lmstudio", "amazon-bedrock"}
_TOP_LEVEL_PROVIDER = re.compile(r'^(\s*model_provider\s*=\s*)(["\'])(.*?)(\2)(\s*(?:#.*)?)$')


@dataclass(frozen=True)
class ModelProviderConfigStatus:
    path: Path
    valid: bool
    selected: str
    available: tuple[str, ...]
    reason: str


def inspect_model_provider_config(codex_home: Path) -> ModelProviderConfigStatus:
    path = codex_home / "config.toml"
    if not path.is_file():
        return ModelProviderConfigStatus(path, True, "openai", tuple(sorted(BUILTIN_MODEL_PROVIDERS)), "使用内置 openai")
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ModelProviderConfigStatus(path, False, "", (), f"无法读取 config.toml：{exc}")
    try:
        data = _parse_toml(content)
    except ValueError as exc:
        return ModelProviderConfigStatus(path, False, "", (), f"config.toml 格式错误：{exc}")

    selected = str(data.get("model_provider") or "openai").strip()
    custom = data.get("model_providers")
    custom_names = set(custom) if isinstance(custom, dict) else set()
    available = tuple(sorted(BUILTIN_MODEL_PROVIDERS | custom_names))
    if selected in BUILTIN_MODEL_PROVIDERS or selected in custom_names:
        return ModelProviderConfigStatus(path, True, selected, available, f"供应商 {selected} 可用")
    return ModelProviderConfigStatus(
        path,
        False,
        selected,
        available,
        f'model_provider = "{selected}"，但缺少 [model_providers.{selected}] 定义',
    )


def effective_model_provider(codex_home: Path) -> str:
    status = inspect_model_provider_config(codex_home)
    return status.selected if status.valid and status.selected else "openai"


def resolve_session_model_provider(codex_home: Path, original: str) -> str:
    provider = str(original or "").strip()
    provider_key = provider.casefold()
    if provider_key in BUILTIN_MODEL_PROVIDERS:
        return provider_key
    status = inspect_model_provider_config(codex_home)
    configured = {
        name.casefold(): name
        for name in status.available
        if name.casefold() not in BUILTIN_MODEL_PROVIDERS
    }
    return configured.get(provider_key, "openai")


def repair_model_provider_to_openai(codex_home: Path) -> Path:
    status = inspect_model_provider_config(codex_home)
    if status.valid:
        raise ValueError("config.toml 的模型供应商配置已经有效")
    if not status.selected:
        raise ValueError(status.reason)
    path = status.path
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    replaced = False
    in_top_level = True
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("["):
            in_top_level = False
        if not in_top_level:
            continue
        match = _TOP_LEVEL_PROVIDER.match(line.rstrip("\r\n"))
        if not match:
            continue
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        lines[index] = f'{match.group(1)}"openai"{match.group(5)}{newline}'
        replaced = True
        break
    if not replaced:
        raise ValueError("未找到可安全修改的顶层 model_provider 配置")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"config.toml.sync-backup-{stamp}")
    shutil.copy2(path, backup)
    temporary = path.with_suffix(".toml.tmp")
    temporary.write_text("".join(lines), encoding="utf-8")
    temporary.replace(path)
    return backup


def _parse_toml(content: str) -> dict[str, Any]:
    if tomllib is not None:
        try:
            return tomllib.loads(content)
        except Exception as exc:
            raise ValueError(str(exc)) from exc
    return _parse_toml_fallback(content)


def _parse_toml_fallback(content: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    providers: dict[str, dict[str, Any]] = {}
    current_table = ""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_table = line[1:-1].strip()
            if current_table.startswith("model_providers."):
                name = current_table[len("model_providers."):].strip().strip('"\'')
                if name:
                    providers.setdefault(name, {})
            continue
        if current_table:
            continue
        match = re.match(r'^model_provider\s*=\s*(["\'])(.*?)\1\s*(?:#.*)?$', line)
        if match:
            result["model_provider"] = match.group(2)
    if providers:
        result["model_providers"] = providers
    return result
