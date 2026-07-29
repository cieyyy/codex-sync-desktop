from __future__ import annotations

import ctypes
import os
import tkinter as tk
from dataclasses import dataclass
from typing import Callable

from .ui_theme import COLORS


TITLEBAR_HEIGHT = 42


def draw_sync_mark(canvas: tk.Canvas, size: int = 24) -> None:
    """Draw the product mark using scalable canvas primitives."""
    canvas.delete("all")
    scale = size / 24
    width = max(2, round(2 * scale))
    canvas.create_oval(2 * scale, 8 * scale, 8 * scale, 14 * scale, fill=COLORS["primary"], outline="")
    canvas.create_oval(16 * scale, 10 * scale, 22 * scale, 16 * scale, fill=COLORS["cyan"], outline="")
    canvas.create_arc(
        5 * scale,
        2 * scale,
        20 * scale,
        15 * scale,
        start=35,
        extent=165,
        style="arc",
        outline=COLORS["primary"],
        width=width,
    )
    canvas.create_polygon(
        18 * scale,
        2 * scale,
        22 * scale,
        5 * scale,
        17 * scale,
        7 * scale,
        fill=COLORS["primary"],
        outline="",
    )
    canvas.create_arc(
        4 * scale,
        9 * scale,
        19 * scale,
        22 * scale,
        start=215,
        extent=165,
        style="arc",
        outline=COLORS["cyan"],
        width=width,
    )
    canvas.create_polygon(
        6 * scale,
        22 * scale,
        2 * scale,
        19 * scale,
        7 * scale,
        17 * scale,
        fill=COLORS["cyan"],
        outline="",
    )


class ChromeButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Widget,
        kind: str,
        command: Callable[[], None],
        *,
        danger: bool = False,
    ) -> None:
        super().__init__(
            parent,
            width=46,
            height=TITLEBAR_HEIGHT,
            background=COLORS["surface"],
            highlightthickness=0,
            borderwidth=0,
            takefocus=1,
            cursor="hand2",
        )
        self.kind = kind
        self.command = command
        self.danger = danger
        self.bind("<Enter>", lambda _event: self._paint(True))
        self.bind("<Leave>", lambda _event: self._paint(False))
        self.bind("<ButtonRelease-1>", lambda _event: self.command())
        self.bind("<Return>", lambda _event: self.command())
        self.bind("<space>", lambda _event: self.command())
        self.bind("<FocusIn>", lambda _event: self._paint(True))
        self.bind("<FocusOut>", lambda _event: self._paint(False))
        self._paint(False)

    def _paint(self, active: bool) -> None:
        background = COLORS["danger"] if active and self.danger else COLORS["surface_alt"] if active else COLORS["surface"]
        self.configure(background=background)
        self.delete("glyph")
        color = COLORS["text"]
        if self.kind == "minimize":
            self.create_line(18, 22, 28, 22, fill=color, width=2, tags="glyph")
        elif self.kind == "maximize":
            self.create_rectangle(18, 15, 28, 25, outline=color, width=1, tags="glyph")
        else:
            self.create_line(18, 16, 28, 26, fill=color, width=1.5, tags="glyph")
            self.create_line(28, 16, 18, 26, fill=color, width=1.5, tags="glyph")


@dataclass
class DragPoint:
    screen_x: int
    screen_y: int
    window_x: int
    window_y: int


class WindowChrome:
    """Borderless Windows frame with a native-feeling dark custom title bar."""

    def __init__(self, window: tk.Tk, title: str, close_command: Callable[[], None]) -> None:
        self.window = window
        self.drag_point: DragPoint | None = None
        self.normal_geometry = ""
        self.maximized = False
        self.enabled = os.name == "nt"

        if self.enabled:
            window.overrideredirect(True)

        self.frame = tk.Frame(
            window,
            background=COLORS["background"],
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["cyan"],
            highlightthickness=1 if self.enabled else 0,
            borderwidth=0,
        )
        self.frame.pack(fill="both", expand=True)

        if self.enabled:
            self.titlebar = tk.Frame(self.frame, height=TITLEBAR_HEIGHT, background=COLORS["surface"], borderwidth=0)
            self.titlebar.pack(fill="x")
            self.titlebar.pack_propagate(False)

            logo = tk.Canvas(
                self.titlebar,
                width=24,
                height=24,
                background=COLORS["surface"],
                highlightthickness=0,
                borderwidth=0,
            )
            logo.pack(side="left", padx=(14, 9))
            draw_sync_mark(logo)

            label = tk.Label(
                self.titlebar,
                text=title,
                background=COLORS["surface"],
                foreground=COLORS["text"],
                font=("Segoe UI Semibold", 10),
            )
            label.pack(side="left")

            ChromeButton(self.titlebar, "close", close_command, danger=True).pack(side="right")
            ChromeButton(self.titlebar, "maximize", self.toggle_maximize).pack(side="right")
            ChromeButton(self.titlebar, "minimize", self.minimize).pack(side="right")

            for widget in (self.titlebar, logo, label):
                widget.bind("<ButtonPress-1>", self._start_drag)
                widget.bind("<B1-Motion>", self._drag)
                widget.bind("<Double-Button-1>", lambda _event: self.toggle_maximize())

            self.window.after_idle(self._show_in_taskbar)

        self.body = tk.Frame(self.frame, background=COLORS["background"], borderwidth=0)
        self.body.pack(fill="both", expand=True)

    def _show_in_taskbar(self) -> None:
        if not self.enabled:
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.window.winfo_id())
            get_window_long = ctypes.windll.user32.GetWindowLongW
            set_window_long = ctypes.windll.user32.SetWindowLongW
            extended_style = get_window_long(hwnd, -20)
            extended_style = (extended_style & ~0x00000080) | 0x00040000
            set_window_long(hwnd, -20, extended_style)
            self.window.withdraw()
            self.window.after(10, self.window.deiconify)
        except (AttributeError, OSError):
            pass

    def _start_drag(self, event: tk.Event) -> None:
        if self.maximized:
            return
        self.drag_point = DragPoint(event.x_root, event.y_root, self.window.winfo_x(), self.window.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if self.drag_point is None or self.maximized:
            return
        x = self.drag_point.window_x + event.x_root - self.drag_point.screen_x
        y = self.drag_point.window_y + event.y_root - self.drag_point.screen_y
        self.window.geometry(f"+{x}+{max(0, y)}")

    def minimize(self) -> None:
        if not self.enabled:
            self.window.iconify()
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.window.winfo_id())
            ctypes.windll.user32.ShowWindow(hwnd, 6)
        except (AttributeError, OSError):
            self.window.iconify()

    def toggle_maximize(self) -> None:
        if not self.enabled:
            return
        if self.maximized:
            if self.normal_geometry:
                self.window.geometry(self.normal_geometry)
            self.maximized = False
            return
        self.normal_geometry = self.window.geometry()
        left, top, right, bottom = self._work_area()
        self.window.geometry(f"{right - left}x{bottom - top}+{left}+{top}")
        self.maximized = True

    @staticmethod
    def _work_area() -> tuple[int, int, int, int]:
        class Rect(ctypes.Structure):
            _fields_ = (("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long))

        rect = Rect()
        try:
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            pass
        return 0, 0, 1120, 760
