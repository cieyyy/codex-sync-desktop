"""Readable diagnostics with explicit row and column dividers."""
import tkinter as tk
from tkinter import ttk

from .ui_theme import COLORS


class DiagnosticTable(ttk.Frame):
    def __init__(self, parent, rows):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=COLORS['background'], highlightthickness=1, highlightbackground=COLORS['border'])
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=scroll.set)
        self.body = tk.Frame(self.canvas, background=COLORS['border'])
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self.body.columnconfigure(0, minsize=165)
        self.body.columnconfigure(1, minsize=90)
        self.body.columnconfigure(2, weight=1)
        self.details = []
        for row_index, values in enumerate([('检查项', '状态', '详情'), *rows]):
            surface = COLORS['surface_alt'] if row_index == 0 else COLORS['surface'] if row_index % 2 else COLORS['background']
            for column, text in enumerate(values):
                foreground = COLORS['text_muted'] if row_index == 0 else COLORS['text']
                if column == 1 and row_index:
                    if str(text) in ('正常', '已登录', '可用'):
                        foreground = COLORS['success']
                    elif str(text) in ('失败', '异常', '缺失', '未登录'):
                        foreground = COLORS['danger']
                cell = tk.Label(self.body, text=str(text), background=surface, foreground=foreground,
                                anchor='w', justify='left', padx=14, pady=14,
                                font=('TkDefaultFont', 12, 'bold') if row_index == 0 else ('TkDefaultFont', 12))
                cell.grid(row=row_index, column=column, sticky='nsew', padx=(1, 0), pady=(1, 0))
                if column == 2:
                    self.details.append(cell)
                cell.bind('<MouseWheel>', self._scroll)
        self.canvas.bind('<Configure>', self._resize)
        self.canvas.bind('<MouseWheel>', self._scroll)
        self.body.bind('<Configure>', lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        for cell in self.details:
            cell.configure(wraplength=max(100, event.width - 290))

    def _scroll(self, event):
        if self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'
