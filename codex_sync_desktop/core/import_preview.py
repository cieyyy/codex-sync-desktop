from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import ImportItem, ImportPlan
from .titles import is_usable_title


PREVIEW_MAX_BYTES = 512 * 1024
PREVIEW_MAX_RECORDS = 240
FAILURE_ACTIONS = ("missing-source", "invalid-source-hash")


def items_for_category(plan: ImportPlan, category: str) -> list[ImportItem]:
    if category == "failure":
        return [item for item in plan.items if item.action in FAILURE_ACTIONS]
    if category == "title-update":
        return [item for item in plan.items if item.task_id in plan.title_updates]
    return [item for item in plan.items if item.action == category]


def normalize_title(value: str) -> str:
    title = " ".join(str(value or "").split()).strip()[:500]
    if not is_usable_title(title):
        raise ValueError("标题不能为空，也不能使用系统指令作为标题。")
    return title


def apply_title_overrides(plan: ImportPlan, overrides: Mapping[str, str]) -> int:
    items_by_task = {item.task_id: item for item in plan.items if item.task_id}
    applied = 0
    for task_id, value in overrides.items():
        item = items_by_task.get(task_id)
        if item is None:
            continue
        title = normalize_title(value)
        if title == item.local_title:
            plan.title_updates.pop(task_id, None)
        else:
            plan.title_updates[task_id] = title
        applied += 1
    return applied


def preview_versions(item: ImportItem) -> list[tuple[str, str]]:
    versions: list[tuple[str, str]] = []
    if item.source.is_file():
        versions.append(("来源设备", render_session_path(item.source)))
    if item.destination.is_file():
        versions.append(("本机", render_session_path(item.destination)))
    if item.merged_content is not None:
        versions.append(("合并后", render_session_bytes(item.merged_content)))
    if not versions:
        reason = item.detail or "文件不存在，无法读取内容。"
        versions.append(("详情", f"无法预览会话内容。\n\n原因：{reason}"))
    return versions


def render_session_path(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read(PREVIEW_MAX_BYTES + 1)
    except OSError as exc:
        return f"无法读取文件。\n\n原因：{exc}"
    truncated = len(raw) > PREVIEW_MAX_BYTES
    return render_session_bytes(raw[:PREVIEW_MAX_BYTES], truncated=truncated)


def render_session_bytes(content: bytes, *, truncated: bool = False) -> str:
    rendered: list[str] = []
    records = 0
    for raw_line in content.decode("utf-8", errors="replace").splitlines():
        if records >= PREVIEW_MAX_RECORDS:
            truncated = True
            break
        try:
            item = json.loads(raw_line)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        record = _render_record(item)
        if not record:
            continue
        rendered.append(record)
        records += 1
    if not rendered:
        rendered.append("没有可显示的文字记录。")
    if truncated:
        rendered.append("\n—— 预览已截断；正式导入仍会处理完整文件 ——")
    return "\n\n".join(rendered)


def _render_record(item: Mapping[str, Any]) -> str:
    payload = item.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    timestamp = str(item.get("timestamp") or payload.get("timestamp") or "").strip()
    prefix = f"[{timestamp}] " if timestamp else ""
    item_type = str(item.get("type") or "")
    payload_type = str(payload.get("type") or "")

    if item_type == "event_msg" and payload_type in ("user_message", "agent_message"):
        label = "用户" if payload_type == "user_message" else "助手"
        text = str(payload.get("message") or "").strip()
        return f"{prefix}{label}\n{text}" if text else ""

    if item_type == "response_item" and payload_type == "message":
        role = str(payload.get("role") or "消息")
        label = {"user": "用户", "assistant": "助手", "developer": "开发者"}.get(role, role)
        text = _content_text(payload.get("content"))
        return f"{prefix}{label}\n{text}" if text else ""

    if item_type == "response_item" and payload_type == "function_call":
        name = str(payload.get("name") or "工具")
        arguments = _display_value(payload.get("arguments"))
        return f"{prefix}命令 / 工具调用：{name}\n{arguments}".rstrip()

    if item_type == "response_item" and payload_type in ("function_call_output", "custom_tool_call_output"):
        output = _display_value(payload.get("output") or payload.get("content"))
        return f"{prefix}工具输出\n{output}".rstrip()

    if payload_type in ("reasoning", "token_count", "task_started", "task_complete", "task_failed"):
        text = _display_value(payload.get("text") or payload.get("message") or payload)
        labels = {
            "reasoning": "推理",
            "token_count": "Token",
            "task_started": "任务开始",
            "task_complete": "任务完成",
            "task_failed": "任务失败",
        }
        return f"{prefix}{labels[payload_type]}\n{text}".rstrip()

    if item_type == "session_meta":
        session_id = str(payload.get("id") or payload.get("session_id") or "")
        cwd = str(payload.get("cwd") or "")
        return f"{prefix}会话信息\nTask ID：{session_id}\n项目目录：{cwd}".rstrip()

    return ""


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, Iterable) or isinstance(content, (bytes, bytearray, Mapping)):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        text = block.get("text") or block.get("content")
        if text:
            parts.append(str(text))
    return "\n".join(parts).strip()


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)
