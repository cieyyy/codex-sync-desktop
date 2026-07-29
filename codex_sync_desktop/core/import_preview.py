from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .models import ImportItem, ImportPlan
from .titles import is_usable_title


FAILURE_ACTIONS = ("missing-source", "invalid-source-hash")


@dataclass(frozen=True)
class PreviewSource:
    label: str
    path: Path | None = None
    content: bytes | None = None
    plain_text: str = ""

    def iter_records(self) -> Iterator[str]:
        if self.path is not None:
            yield from iter_session_path(self.path)
            return
        if self.content is not None:
            yield from iter_session_bytes(self.content)
            return
        yield self.plain_text or "没有可显示的文字记录。"


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


def preview_sources(item: ImportItem) -> list[PreviewSource]:
    versions: list[PreviewSource] = []
    if item.source.is_file():
        versions.append(PreviewSource("来源设备", path=item.source))
    if item.destination.is_file():
        versions.append(PreviewSource("本机", path=item.destination))
    if item.merged_content is not None:
        versions.append(PreviewSource("合并后", content=item.merged_content))
    if not versions:
        reason = item.detail or "文件不存在，无法读取内容。"
        versions.append(PreviewSource("详情", plain_text=f"无法预览会话内容。\n\n原因：{reason}"))
    return versions


def preview_versions(item: ImportItem) -> list[tuple[str, str]]:
    """Render every version completely for non-UI callers and tests."""
    return [(source.label, "\n\n".join(source.iter_records())) for source in preview_sources(item)]


def render_session_path(path: Path) -> str:
    return "\n\n".join(iter_session_path(path))


def render_session_bytes(content: bytes) -> str:
    return "\n\n".join(iter_session_bytes(content))


def iter_session_path(path: Path) -> Iterator[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            yield from _iter_rendered_lines(handle)
    except OSError as exc:
        yield f"无法读取文件。\n\n原因：{exc}"


def iter_session_bytes(content: bytes) -> Iterator[str]:
    with io.StringIO(content.decode("utf-8", errors="replace")) as handle:
        yield from _iter_rendered_lines(handle)


def _iter_rendered_lines(lines: Iterable[str]) -> Iterator[str]:
    rendered = False
    for raw_line in lines:
        try:
            item = json.loads(raw_line)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        record = _render_record(item)
        if not record:
            continue
        rendered = True
        yield record
    if not rendered:
        yield "没有可显示的文字记录。"


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
