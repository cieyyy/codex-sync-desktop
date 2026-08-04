from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Iterator, Mapping

from .core.import_preview import PreviewSource, items_for_category, normalize_title, preview_sources
from .core.models import ImportItem, ImportPlan
from .ui_theme import COLORS, center_window


CATEGORY_TITLES = {
    "copy": "新增会话",
    "identical": "内容相同",
    "conflict": "自动合并",
    "failure": "校验失败",
    "title-update": "标题更新",
}


class ImportPreviewDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        plan: ImportPlan,
        category: str,
        title_overrides: Mapping[str, str],
        on_title_saved: Callable[[str, str], None],
    ) -> None:
        super().__init__(parent)
        self.plan = plan
        self.category = category
        self.items = items_for_category(plan, category)
        self.title_overrides = title_overrides
        self.on_title_saved = on_title_saved
        self.current_item: ImportItem | None = None
        self.current_item_iid = ""
        self.current_versions: dict[str, PreviewSource] = {}
        self.preview_iterator: Iterator[str] | None = None
        self.preview_generation = 0
        self.preview_record_count = 0
        self._loading_item = False

        title = CATEGORY_TITLES.get(category, "导入详情")
        self.title(f"{title} · 预览导入")
        self.configure(background=COLORS["background"])
        self.minsize(900, 620)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _event: self._close())
        self.bind("<Control-s>", lambda _event: self._save_title())

        self._build_ui(title)
        center_window(self, parent, 1080, 720)
        self.lift(parent)
        self.grab_set()
        if self.items:
            first = self.item_tree.get_children()[0]
            self.item_tree.selection_set(first)
            self.item_tree.focus(first)
            self._select_item()
        self.item_tree.focus_set()

    def _build_ui(self, title: str) -> None:
        header = ttk.Frame(self, padding=(20, 18, 20, 12))
        header.pack(fill="x")
        ttk.Label(header, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text=f"来源设备：{self.plan.source_label or self.plan.source_device} · 共 {len(self.items)} 个会话",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        body = ttk.Frame(self, padding=(20, 0, 20, 14))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=5)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Panel.TFrame", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(left, text="会话列表", style="PanelSection.TLabel").pack(anchor="w", pady=(0, 8))
        list_frame = ttk.Frame(left, style="Panel.TFrame")
        list_frame.pack(fill="both", expand=True)
        self.item_tree = ttk.Treeview(
            list_frame,
            columns=("title", "task"),
            show="headings",
            selectmode="browse",
        )
        self.item_tree.heading("title", text="标题")
        self.item_tree.heading("task", text="Task ID")
        self.item_tree.column("title", width=210, minwidth=140, stretch=True)
        self.item_tree.column("task", width=120, minwidth=100, stretch=False)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.item_tree.yview)
        self.item_tree.configure(yscrollcommand=scrollbar.set)
        self.item_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.item_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_item())
        for index, item in enumerate(self.items):
            title_text = self._initial_title(item) or "未命名会话"
            task_text = item.task_id[-12:] if item.task_id else "不可用"
            self.item_tree.insert("", "end", iid=str(index), values=(title_text, task_text))

        right = ttk.Frame(body, style="Panel.TFrame", padding=14)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(7, weight=1)

        ttk.Label(right, text="最终导入标题", style="PanelSection.TLabel").grid(row=0, column=0, sticky="w")
        title_row = ttk.Frame(right, style="Panel.TFrame")
        title_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        title_row.columnconfigure(0, weight=1)
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(title_row, textvariable=self.title_var)
        self.title_entry.grid(row=0, column=0, sticky="ew")
        self.title_entry.bind("<FocusOut>", lambda _event: self._validate_title())
        self.save_button = ttk.Button(
            title_row,
            text="保存标题",
            style="Accent.TButton",
            command=self._save_title,
        )
        self.save_button.grid(row=0, column=1, padx=(8, 0))
        self.title_error = ttk.Label(right, text="", style="PanelMuted.TLabel")
        self.title_error.grid(row=2, column=0, sticky="w", pady=(4, 8))

        self.meta_label = ttk.Label(
            right,
            text="请选择会话",
            style="PanelMuted.TLabel",
            justify="left",
        )
        self.meta_label.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        preview_header = ttk.Frame(right, style="Panel.TFrame")
        preview_header.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(preview_header, text="文字内容预览", style="PanelSection.TLabel").pack(side="left")
        self.preview_status = ttk.Label(preview_header, text="", style="PanelMuted.TLabel")
        self.preview_status.pack(side="left", padx=(10, 0))
        ttk.Label(preview_header, text="版本", style="PanelMuted.TLabel").pack(side="right", padx=(8, 0))
        self.version_var = tk.StringVar()
        self.version_combo = ttk.Combobox(
            preview_header,
            textvariable=self.version_var,
            state="readonly",
            width=13,
        )
        self.version_combo.pack(side="right")
        self.version_combo.bind("<<ComboboxSelected>>", lambda _event: self._show_version())

        text_frame = ttk.Frame(right, style="Panel.TFrame")
        text_frame.grid(row=7, column=0, sticky="nsew")
        self.preview_text = tk.Text(
            text_frame,
            wrap="word",
            state="disabled",
            font=("TkFixedFont", 10),
            background=COLORS["surface_alt"],
            foreground=COLORS["text"],
            insertbackground=COLORS["primary"],
            selectbackground=COLORS["secondary"],
            selectforeground=COLORS["text"],
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["border"],
            highlightthickness=1,
            borderwidth=0,
            padx=12,
            pady=12,
        )
        text_scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=text_scrollbar.set)
        self.preview_text.pack(side="left", fill="both", expand=True)
        text_scrollbar.pack(side="right", fill="y")

        footer = ttk.Frame(self, padding=(20, 0, 20, 18))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text="仅修改标题；会话内容保持只读。标题将在正式导入时应用。",
            style="Muted.TLabel",
        ).pack(side="left")
        ttk.Button(footer, text="关闭", command=self._close).pack(side="right")

    def _initial_title(self, item: ImportItem) -> str:
        if item.task_id in self.title_overrides:
            return self.title_overrides[item.task_id]
        if item.task_id in self.plan.title_updates:
            return self.plan.title_updates[item.task_id]
        return item.source_title or item.local_title

    def _select_item(self) -> None:
        selection = self.item_tree.selection()
        if not selection:
            return
        next_iid = selection[0]
        if self.current_item is not None and self.current_item_iid and next_iid != self.current_item_iid:
            if not self._commit_title(show_feedback=False):
                self.item_tree.selection_set(self.current_item_iid)
                self.item_tree.focus(self.current_item_iid)
                self.title_entry.focus_set()
                return
        index = int(next_iid)
        item = self.items[index]
        self.current_item = item
        self.current_item_iid = next_iid
        self._loading_item = True
        self.title_var.set(self._initial_title(item))
        self.title_error.configure(text="")
        editable = bool(item.task_id)
        self.title_entry.configure(state="normal" if editable else "disabled")
        self.save_button.configure(state="normal" if editable else "disabled")
        self._loading_item = False

        source_title = item.source_title or "无"
        local_title = item.local_title or "无"
        detail = item.detail or "无"
        self.meta_label.configure(
            text=(
                f"Task ID：{item.task_id or '不可用'}\n"
                f"来源标题：{source_title}\n"
                f"本机标题：{local_title}\n"
                f"文件：{item.relative_path}\n"
                f"说明：{detail}"
            )
        )
        versions = preview_sources(item)
        self.current_versions = {source.label: source for source in versions}
        labels = [source.label for source in versions]
        self.version_combo["values"] = labels
        self.version_var.set(labels[0])
        self._show_version()

    def _show_version(self) -> None:
        source = self.current_versions.get(self.version_var.get())
        self._cancel_preview_loading()
        self.preview_generation += 1
        generation = self.preview_generation
        self.preview_record_count = 0
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.yview_moveto(0)
        if source is None:
            self.preview_text.insert("1.0", "没有可显示的文字记录。")
            self.preview_text.configure(state="disabled")
            self.preview_status.configure(text="加载失败")
            return
        self.preview_iterator = source.iter_records()
        self.preview_status.configure(text="正在加载完整预览…")
        self._append_preview_batch(generation)

    def _append_preview_batch(self, generation: int) -> None:
        if generation != self.preview_generation or self.preview_iterator is None:
            return
        appended = 0
        appended_bytes = 0
        try:
            while appended < 40 and appended_bytes < 128 * 1024:
                record = next(self.preview_iterator)
                if self.preview_record_count:
                    self.preview_text.insert("end", "\n\n")
                self.preview_text.insert("end", record)
                self.preview_record_count += 1
                appended += 1
                appended_bytes += len(record.encode("utf-8", errors="replace"))
        except StopIteration:
            self.preview_iterator = None
            self.preview_text.configure(state="disabled")
            self.preview_status.configure(text=f"完整预览 · {self.preview_record_count} 条")
            return
        self.after(1, lambda: self._append_preview_batch(generation))

    def _cancel_preview_loading(self) -> None:
        iterator = self.preview_iterator
        self.preview_iterator = None
        if iterator is not None:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()

    def _validate_title(self) -> bool:
        if self._loading_item or not self.current_item or not self.current_item.task_id:
            return True
        return self._commit_title(show_feedback=False)

    def _save_title(self) -> None:
        self._commit_title(show_feedback=True)

    def _commit_title(self, *, show_feedback: bool) -> bool:
        item = self.current_item
        if item is None or not item.task_id:
            return True
        if not self.title_var.get().strip() and not self._initial_title(item):
            if show_feedback:
                self.title_error.configure(text="标题不能为空。", foreground=COLORS["danger"])
                self.title_entry.focus_set()
                return False
            return True
        try:
            title = normalize_title(self.title_var.get())
        except ValueError as exc:
            self.title_error.configure(text=str(exc), foreground=COLORS["danger"])
            self.title_entry.focus_set()
            return False
        self.title_var.set(title)
        if title != self._initial_title(item):
            self.on_title_saved(item.task_id, title)
        if self.current_item_iid:
            self.item_tree.set(self.current_item_iid, "title", title)
        feedback = "已保存，将在正式导入时应用" if show_feedback else "标题有效，修改已暂存"
        self.title_error.configure(text=feedback, foreground=COLORS["primary"] if show_feedback else COLORS["text_muted"])
        return True

    def _close(self) -> None:
        if self.current_item and self.current_item.task_id:
            current = self.title_var.get()
            initial = self._initial_title(self.current_item)
            if current.strip() and current != initial:
                if messagebox.askyesno("保存标题修改", "当前标题尚未保存，是否保存后关闭？", parent=self):
                    if not self._commit_title(show_feedback=True):
                        return
        self._cancel_preview_loading()
        self.preview_generation += 1
        self.grab_release()
        self.destroy()
