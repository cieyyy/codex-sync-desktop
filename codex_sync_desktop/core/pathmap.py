from __future__ import annotations

from typing import Mapping


def map_path(value: str, mappings: Mapping[str, str]) -> str:
    if not value:
        return value
    normalized = value.replace("\\", "/")
    best_source = ""
    best_target = ""
    for source, target in mappings.items():
        candidate = source.replace("\\", "/").rstrip("/")
        if normalized.lower() == candidate.lower() or normalized.lower().startswith(candidate.lower() + "/"):
            if len(candidate) > len(best_source):
                best_source, best_target = candidate, target.rstrip("/\\")
    if not best_source:
        return value
    suffix = normalized[len(best_source):].lstrip("/")
    separator = "\\" if "\\" in best_target else "/"
    return best_target + (separator + suffix.replace("/", separator) if suffix else "")
