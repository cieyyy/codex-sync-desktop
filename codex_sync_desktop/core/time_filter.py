"""Local calendar date ranges for conversation activity, independent of upload times."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

TIME_FILTER_OPTIONS = ("全部时间", "最近7天", "最近30天", "最近90天", "最近180天", "最近365天", "自定义日期")


def resolve_time_range(mode="全部时间", start="", end="", *, now=None):
    now = now or datetime.now()
    if mode not in TIME_FILTER_OPTIONS:
        raise ValueError("请选择有效的同步时间范围")
    if mode == "全部时间":
        return None, None
    if mode == "自定义日期":
        def parse(value):
            if not value.strip():
                return None
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
                raise ValueError("日期格式应为 YYYY-MM-DD，例如 2026-11-01")
            try:
                return date.fromisoformat(value.strip())
            except ValueError as exc:
                raise ValueError("日期无效，请输入实际存在的日期") from exc
        first, last = parse(start), parse(end)
        if first is None and last is None:
            raise ValueError("自定义日期至少填写一个日期")
        if first and last and first > last:
            raise ValueError("开始日期不能晚于结束日期")
    else:
        days = int(re.search(r"\d+", mode).group())
        first, last = now.date() - timedelta(days=days - 1), now.date()
    # Naive local midnight uses the OS timezone rules for each date, including DST.
    def midnight(day):
        value = datetime.combine(day, time.min)
        return value.replace(tzinfo=now.tzinfo).timestamp() if now.tzinfo else value.timestamp()
    return (midnight(first) if first else None,
            midnight(last + timedelta(days=1)) if last else None)


def last_activity(records):
    latest = None
    for record in records:
        payload = record.get("payload")
        values = [record.get("timestamp")]
        if isinstance(payload, dict) and record.get("type") == "session_meta":
            values.append(payload.get("timestamp"))
        for value in values:
            if not isinstance(value, str):
                continue
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                stamp = parsed.timestamp()
            except (ValueError, OverflowError, OSError):
                continue
            latest = max(latest, stamp) if latest is not None else stamp
    return latest
