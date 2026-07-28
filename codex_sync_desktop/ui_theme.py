from __future__ import annotations

from typing import Any


COLORS = {
    "background": "#050816",
    "surface": "#0B1228",
    "surface_alt": "#101A38",
    "sidebar": "#070D21",
    "border": "#1D2B53",
    "primary": "#38BDF8",
    "primary_hover": "#7DD3FC",
    "primary_pressed": "#0EA5E9",
    "secondary": "#1D4ED8",
    "secondary_hover": "#2563EB",
    "secondary_pressed": "#1E40AF",
    "button_disabled": "#111C3A",
    "text": "#F8FAFC",
    "text_muted": "#91A4CC",
    "text_disabled": "#617199",
    "cyan": "#67E8F9",
    "success": "#34D399",
    "danger": "#F43F5E",
    "danger_hover": "#FB7185",
    "warning": "#F59E0B",
}


def centered_geometry(
    width: int,
    height: int,
    parent_x: int,
    parent_y: int,
    parent_width: int,
    parent_height: int,
    screen_width: int,
    screen_height: int,
    margin: int = 16,
) -> str:
    usable_width = max(320, screen_width - margin * 2)
    usable_height = max(240, screen_height - margin * 2)
    actual_width = min(width, usable_width)
    actual_height = min(height, usable_height)
    x = parent_x + max(0, (parent_width - actual_width) // 2)
    y = parent_y + max(0, (parent_height - actual_height) // 2)
    x = min(max(margin, x), max(margin, screen_width - actual_width - margin))
    y = min(max(margin, y), max(margin, screen_height - actual_height - margin))
    return f"{actual_width}x{actual_height}+{x}+{y}"


def center_window(window: Any, parent: Any, width: int, height: int) -> None:
    parent.update_idletasks()
    window.update_idletasks()
    geometry = centered_geometry(
        width,
        height,
        parent.winfo_rootx(),
        parent.winfo_rooty(),
        max(parent.winfo_width(), 1),
        max(parent.winfo_height(), 1),
        window.winfo_screenwidth(),
        window.winfo_screenheight(),
    )
    window.geometry(geometry)
