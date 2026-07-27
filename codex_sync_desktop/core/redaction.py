from __future__ import annotations

import re
from typing import Any, Dict, Tuple


MEDIA_PATTERNS = (
    (re.compile(r"data:(?:image|audio|video|application)/[a-z0-9.+-]+;base64,[a-z0-9+/=]+", re.I), "[binary media omitted]"),
    (re.compile(r"<image\b[\s\S]*?</image>", re.I), "[image omitted]"),
    (re.compile(r"<attachment\b[\s\S]*?</attachment>", re.I), "[attachment omitted]"),
    (re.compile(r"!\[[^\]]*]\((?:data:|file:|https?://)[^)]+\)", re.I), "[image omitted]"),
    (re.compile(r"[A-Za-z0-9+/]{4096,}={0,2}"), "[binary content omitted]"),
)

MEDIA_TYPES = {
    "attachment", "audio", "computer_screenshot", "file_attachment", "image",
    "image_url", "input_audio", "input_file", "input_image", "input_video",
    "local_image", "output_audio", "output_image", "screenshot", "video",
}

_OMIT = object()


def sanitize_text(value: Any) -> Tuple[str, int, int]:
    text = str(value or "")
    removed = 0
    for pattern, replacement in MEDIA_PATTERNS:
        text, count = pattern.subn(replacement, text)
        removed += count
    return text, removed, 0


def sanitize_record(item: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, int, int]:
    counts = {"removed": 0}
    clean = _sanitize_value(item, counts, root=True)
    if clean is _OMIT or ("payload" in item and "payload" not in clean):
        return None, counts["removed"], 0
    return clean, counts["removed"], 0


def _sanitize_value(value: Any, counts: Dict[str, int], root: bool = False) -> Any:
    if isinstance(value, str):
        text, removed, _ = sanitize_text(value)
        counts["removed"] += removed
        return text
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, list):
        if _looks_like_byte_array(value):
            counts["removed"] += 1
            return _OMIT
        result = []
        for child in value:
            clean = _sanitize_value(child, counts)
            if clean is not _OMIT:
                result.append(clean)
        return result
    if not isinstance(value, dict):
        return value
    if not root and _is_media_object(value):
        counts["removed"] += 1
        return _OMIT

    result = {}
    for key, child in value.items():
        if _is_inline_binary_field(str(key), child):
            counts["removed"] += 1
            continue
        clean = _sanitize_value(child, counts)
        if clean is not _OMIT:
            result[key] = clean
    return result


def _is_media_object(value: Dict[str, Any]) -> bool:
    item_type = str(value.get("type") or "").lower()
    if item_type in MEDIA_TYPES:
        return True
    mime = str(value.get("mime_type") or value.get("mimeType") or "").lower()
    if re.match(r"^(?:image|audio|video)/", mime):
        return True
    return mime == "application/octet-stream" and any(key in value for key in ("data", "blob", "bytes", "content"))


def _is_inline_binary_field(key: str, value: Any) -> bool:
    normalized = key.lower()
    if re.match(r"^(?:image_url|audio_url|video_url|blob|binary|base64|bytes)$", normalized):
        return True
    if normalized == "data" and isinstance(value, str):
        return bool(re.match(r"^data:(?:image|audio|video|application)/", value, re.I) or _looks_like_large_base64(value))
    return normalized in {"data", "buffer", "bytes"} and isinstance(value, list) and _looks_like_byte_array(value)


def _looks_like_large_base64(value: str) -> bool:
    return len(value) >= 4096 and bool(re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", value))


def _looks_like_byte_array(value: list[Any]) -> bool:
    return len(value) >= 256 and all(isinstance(entry, int) and 0 <= entry <= 255 for entry in value)
