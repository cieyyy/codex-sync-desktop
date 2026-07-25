from __future__ import annotations

import re
from typing import Any, Dict, Tuple


MEDIA_PATTERNS = (
    re.compile(r"data:(?:image|audio|video|application)/[a-z0-9.+-]+;base64,[a-z0-9+/=]+", re.I),
    re.compile(r"<image\b[\s\S]*?</image>", re.I),
    re.compile(r"<attachment\b[\s\S]*?</attachment>", re.I),
    re.compile(r"!\[[^\]]*]\((?:data:|file:|https?://)[^)]+\)", re.I),
    re.compile(r"[A-Za-z0-9+/]{4096,}={0,2}"),
)

SECRET_PATTERNS = (
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I), "[PRIVATE_KEY_REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[OPENAI_KEY_REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[GITHUB_TOKEN_REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[AWS_ACCESS_KEY_REDACTED]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[GOOGLE_API_KEY_REDACTED]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"), "[SLACK_TOKEN_REDACTED]"),
    (re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"), "[NPM_TOKEN_REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[JWT_REDACTED]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{24,}", re.I), "Bearer [TOKEN_REDACTED]"),
    (re.compile(r"\b(password|passwd|pwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)([\"']?)(\s*[:=]\s*)[\"']?[^\s\"',;]{6,}[\"']?", re.I), r"\1\2\3[SECRET_REDACTED]"),
    (re.compile(r"\b(https?|postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?):\/\/([^:\s/@]+):([^@\s/]+)@", re.I), r"\1://\2:[SECRET_REDACTED]@"),
)


def sanitize_text(value: Any) -> Tuple[str, int, int]:
    text = str(value or "")
    media_removed = 0
    secrets_redacted = 0
    for pattern in MEDIA_PATTERNS:
        text, count = pattern.subn("[media omitted]", text)
        media_removed += count
    text = re.sub(
        r"# Files mentioned by the user:[\s\S]*?## My request for Codex:",
        "## My request for Codex:",
        text,
        flags=re.I,
    )
    for pattern, replacement in SECRET_PATTERNS:
        text, count = pattern.subn(replacement, text)
        secrets_redacted += count
    return text.strip(), media_removed, secrets_redacted


def sanitize_record(item: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, int, int]:
    item_type = item.get("type")
    payload = item.get("payload") or {}
    if item_type == "session_meta":
        allowed = (
            "session_id", "id", "forked_from_id", "timestamp", "cwd", "originator",
            "cli_version", "source", "thread_source", "model_provider", "history_mode",
            "multi_agent_version", "context_window",
        )
        clean = {key: payload[key] for key in allowed if key in payload}
        return {"timestamp": item.get("timestamp"), "type": "session_meta", "payload": clean}, 0, 0
    if item_type == "event_msg" and payload.get("type") in ("user_message", "agent_message"):
        text, media, secrets = sanitize_text(payload.get("message"))
        if not text:
            return None, media, secrets
        return {
            "timestamp": item.get("timestamp"),
            "type": "event_msg",
            "payload": {"type": payload["type"], "message": text},
        }, media, secrets
    if item_type == "response_item" and payload.get("type") == "message" and payload.get("role") in ("user", "assistant"):
        content = []
        media = 0
        secrets = 0
        for block in payload.get("content") or []:
            if block.get("type") not in ("input_text", "output_text"):
                media += 1
                continue
            text, block_media, block_secrets = sanitize_text(block.get("text"))
            media += block_media
            secrets += block_secrets
            if text:
                content.append({"type": block["type"], "text": text})
        if not content:
            return None, media, secrets
        clean_payload = {"type": "message", "role": payload["role"], "content": content}
        if "phase" in payload:
            clean_payload["phase"] = payload["phase"]
        return {"timestamp": item.get("timestamp"), "type": "response_item", "payload": clean_payload}, media, secrets
    return None, 0, 0
