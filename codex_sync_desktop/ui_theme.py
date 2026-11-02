from __future__ import annotations

from typing import Any


COLORS = {'background': '#101214', 'surface': '#1b1f24', 'surface_alt': '#23282f', 'sidebar': '#171a1e', 'border': '#30363e', 'primary': '#63d8f4', 'primary_hover': '#8de4f8', 'primary_pressed': '#47bdd9', 'secondary': '#23282f', 'secondary_hover': '#30363e', 'secondary_pressed': '#233e48', 'button_disabled': '#262b31', 'text': '#f1f3f5', 'text_muted': '#a4adb8', 'text_disabled': '#69737e', 'cyan': '#63d8f4', 'success': '#8ad5b0', 'danger': '#f28c9b', 'danger_hover': '#f5a7b2', 'warning': '#e9bf78', 'selection': '#233e48', 'accent_ink': '#10191d'}
DARK_COLORS = dict(COLORS)
LIGHT_COLORS = {
    'background': '#f5f6f8', 'surface': '#ffffff', 'surface_alt': '#e9edf1',
    'sidebar': '#edf0f3', 'border': '#c7cfd8', 'primary': '#006b86',
    'primary_hover': '#00566e', 'primary_pressed': '#00465a',
    'secondary': '#e9edf1', 'secondary_hover': '#c7cfd8',
    'secondary_pressed': '#d5eaf0', 'button_disabled': '#e1e5e9',
    'text': '#1b2530', 'text_muted': '#566473', 'text_disabled': '#74808c',
    'cyan': '#006b86', 'success': '#206c49', 'danger': '#b52b45',
    'danger_hover': '#8e1830', 'warning': '#805500', 'selection': '#d5eaf0',
    'accent_ink': '#fdfefe',
}


def set_palette(appearance: str) -> None:
    # Keep the shared dictionary identity for modules that import COLORS.
    COLORS.update(LIGHT_COLORS if appearance == 'light' else DARK_COLORS)


def recolor_widgets(root: Any, previous: dict[str, str]) -> None:
    """Retheme existing native widgets without rebuilding forms or previews."""
    import tkinter as tk
    from tkinter import ttk
    replacements = {value: COLORS[key] for key, value in previous.items()}

    def replace(value: str) -> str:
        return replacements.get(str(value).lower(), value)

    def visit(widget: Any) -> None:
        if not isinstance(widget, ttk.Widget):
            keys = widget.keys()
            for option in ('background', 'foreground', 'insertbackground', 'selectbackground',
                           'selectforeground', 'highlightbackground', 'highlightcolor'):
                if option in keys:
                    old = widget.cget(option)
                    if replace(old) != old:
                        widget.configure(**{option: replace(old)})
        if isinstance(widget, tk.Text):
            state = widget.cget('state')
            widget.configure(state='normal')
            for tag in widget.tag_names():
                for option in ('background', 'foreground'):
                    old = widget.tag_cget(tag, option)
                    if old and replace(old) != old:
                        widget.tag_configure(tag, **{option: replace(old)})
            widget.configure(state=state)
        if isinstance(widget, tk.Canvas):
            for item in widget.find_all():
                for option in ('fill', 'outline'):
                    if option in widget.itemconfigure(item):
                        old = widget.itemcget(item, option)
                        if old and replace(old) != old:
                            widget.itemconfigure(item, **{option: replace(old)})
        for child in widget.winfo_children():
            visit(child)
    visit(root)


def vertical_scrollbar_required(content_height: int, viewport_height: int, tolerance: int = 0) -> bool:
    """Return whether vertically scrolling is needed for the current viewport."""
    if viewport_height <= 1:
        return False
    return content_height > viewport_height + max(tolerance, 0)


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
