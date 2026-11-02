from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Iterator, Mapping

from .core.import_preview import PreviewSource, DialogueMessage, iter_dialogue, items_for_category, normalize_title, preview_sources, preview_activity, format_activity, sorted_activity_ids
from .core.models import ImportItem, ImportPlan
from .core.projects import normalize_project, project_label, project_detail
from .ui_theme import COLORS, center_window


CATEGORY_TITLES = {
    "skipped-time": "按时间跳过",
    "skipped-existing": "已保护本机会话",
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
        self.activity_times = {str(index): preview_activity(item) for index, item in enumerate(self.items)}
        self.time_descending = True
        self.project_ids = {str(index): normalize_project(item.project)["group_id"] for index, item in enumerate(self.items)}
        groups = {}
        for item in self.items:
            project = normalize_project(item.project)
            group = groups.setdefault(project["group_id"], {"project": project, "count": 0})
            group["count"] += 1
        labels = [project_label(group["project"]) for group in groups.values()]
        self.project_choices = {"全部项目": None}
        for identity, group in sorted(groups.items(), key=lambda pair: project_label(pair[1]["project"])):
            label = project_label(group["project"])
            if labels.count(label) > 1:
                label += " · " + identity[-8:]
            self.project_choices[f"{label}（{group['count']}）"] = identity
        self.last_project_choice = "全部项目"
        self.title_overrides = title_overrides
        self.on_title_saved = on_title_saved
        self.current_item: ImportItem | None = None
        self.current_item_iid = ""
        self.current_versions: dict[str, PreviewSource] = {}
        self.preview_iterator: Iterator[str] | None = None
        self.preview_generation = 0
        self.preview_record_count = 0
        self._loading_item = False
        self.details_visible = False
        self.embedded = False

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
        if not self.embedded:
            header.pack(fill="x")
        ttk.Label(header, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text=f"{self.plan.source_label or self.plan.source_device} · 共 {len(self.items)} 个会话",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        body = ttk.Frame(self, padding=0 if self.embedded else (20, 0, 20, 14))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=5, uniform="preview")
        body.columnconfigure(1, weight=4, uniform="preview")
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, padding=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        ttk.Label(left, text="会话列表", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        filter_row = ttk.Frame(left)
        filter_row.pack(fill="x", pady=(0, 8))
        ttk.Label(filter_row, text="项目", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.project_var = tk.StringVar(value="全部项目")
        self.project_combo = ttk.Combobox(filter_row, textvariable=self.project_var, values=list(self.project_choices), state="readonly", width=18)
        self.project_combo.pack(side="left", fill="x", expand=True)
        self.project_combo.bind("<<ComboboxSelected>>", lambda _event: self._filter_project())
        search_row = ttk.Frame(left)
        search_row.pack(fill="x", pady=(0, 10))
        ttk.Label(search_row, text="搜索标题", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var, width=18)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_var.trace_add("write", lambda *_: self._filter_project())
        list_frame = ttk.Frame(left, style="Panel.TFrame")
        list_frame.pack(fill="both", expand=True)
        self.item_tree = ttk.Treeview(
            list_frame,
            columns=("title", "project", "time"),
            show="headings",
            selectmode="browse",
        )
        self.item_tree.heading("title", text="标题")
        self.item_tree.heading("project", text="来源项目")
        self.item_tree.heading("time", text="最后活动 ↓", command=self._sort_by_time)
        self.item_tree.column("title", width=190, minwidth=80, stretch=True)
        self.item_tree.column("project", width=85, minwidth=65, stretch=False)
        self.item_tree.column("time", width=128, minwidth=122, stretch=False)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.item_tree.yview)
        self.item_tree.configure(yscrollcommand=scrollbar.set)
        self.item_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.item_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_item())
        for index, item in enumerate(self.items):
            title_text = self._initial_title(item) or "未命名会话"
            time_text = format_activity(self.activity_times[str(index)])
            self.item_tree.insert("", "end", iid=str(index), values=(title_text, project_label(item.project), time_text))
        self._sort_by_time(toggle=False)
        ttk.Label(left, text="点击时间表头切换排序 · 北京时间", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

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
        if self.embedded:
            self.title_error.grid_remove()
        ttk.Button(right, text="会话详情", style="Detail.TButton", command=self._toggle_meta).grid(row=0 if self.embedded else 2, column=0, sticky="e", pady=(0, 0) if self.embedded else (4, 8))

        self.meta_label = ttk.Label(
            right,
            text="请选择会话",
            style="PanelMuted.TLabel",
            justify="left",
            wraplength=500,
        )
        right.bind("<Configure>", lambda event: self.meta_label.configure(wraplength=max(220, event.width - 28)), add="+")
        self.meta_label.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        preview_header = ttk.Frame(right, style="Panel.TFrame")
        preview_header.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(preview_header, text="对话预览", style="PanelSection.TLabel").pack(side="left")
        self.preview_status = ttk.Label(preview_header, text="", style="PanelMuted.TLabel")
        self.preview_status.pack(side="left", padx=(8, 0))
        self.version_label = ttk.Label(preview_header, text="版本", style="PanelMuted.TLabel")
        self.version_label.pack(side="right", padx=(8, 0))
        self.version_var = tk.StringVar()
        self.version_combo = ttk.Combobox(
            preview_header,
            textvariable=self.version_var,
            state="readonly",
            width=13,
        )
        self.version_combo.pack(side="right")
        self.version_combo.bind("<<ComboboxSelected>>", lambda _event: self._show_version())

        mode_row = ttk.Frame(right, style="Panel.TFrame")
        mode_row.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        self.preview_mode = tk.StringVar(value="对话模式")
        mode_combo = ttk.Combobox(mode_row, textvariable=self.preview_mode, values=("对话模式", "完整记录"), state="readonly", width=12)
        mode_combo.pack(side="left")
        if self.embedded:
            mode_row.grid_remove()
            mode_combo.pack_forget()
            mode_combo = ttk.Combobox(preview_header, textvariable=self.preview_mode, values=("对话模式", "完整记录"), state="readonly", width=9)
            mode_combo.pack(side="right")
        mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._show_version())
        ttk.Label(mode_row, text="对话模式仅展示你与助手的消息", style="PanelMuted.TLabel").pack(side="left", padx=10)

        text_frame = ttk.Frame(right, style="Panel.TFrame")
        text_frame.grid(row=7, column=0, sticky="nsew")
        self.preview_text = tk.Text(
            text_frame,
            wrap="word",
            height=8,
            state="disabled",
            font=("Helvetica Neue", 12),
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
        self.preview_text.tag_configure("user_header", foreground=COLORS["cyan"], font=("TkDefaultFont", 11, "bold"), lmargin1=28, lmargin2=28, spacing1=14, spacing3=6)
        self.preview_text.tag_configure("assistant_header", foreground=COLORS["success"], font=("TkDefaultFont", 11, "bold"), spacing1=14, spacing3=6)
        self.preview_text.tag_configure("user_body", background=COLORS["selection"], lmargin1=28, lmargin2=28, rmargin=12, spacing1=2, spacing3=3)
        self.preview_text.tag_configure("assistant_body", background=COLORS["surface"], lmargin1=12, lmargin2=12, rmargin=20, spacing1=2, spacing3=3)
        self.preview_text.tag_configure("notice", foreground=COLORS["text_muted"])
        text_scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=text_scrollbar.set)
        self.preview_text.pack(side="left", fill="both", expand=True)
        text_scrollbar.pack(side="right", fill="y")

        footer = ttk.Frame(self, padding=(20, 0, 20, 18))
        if not self.embedded:
            footer.pack(side="bottom", fill="x", before=body)
        ttk.Label(
            footer,
            text="仅修改标题；会话内容保持只读。标题将在正式导入时应用。",
            style="Muted.TLabel",
        ).pack(side="left")
        ttk.Button(footer, text="关闭", command=self._close).pack(side="right")

    def _filter_project(self) -> None:
        if self.current_item is not None and not self._commit_title(show_feedback=False):
            self.project_var.set(self.last_project_choice)
            return
        self.last_project_choice = self.project_var.get()
        selected_group = self.project_choices.get(self.project_var.get())
        query = self.search_var.get().strip().casefold()
        for iid in self.project_ids:
            matches = query in str(self.item_tree.set(iid, "title")).casefold()
            if matches and (selected_group is None or self.project_ids[iid] == selected_group):
                self.item_tree.move(iid, "", "end")
            else:
                self.item_tree.detach(iid)
        self._sort_by_time(toggle=False)
        visible = self.item_tree.get_children()
        if not visible:
            self._empty_preview("没有匹配的会话。可调整项目、搜索词或时间范围。")
        if self.current_item_iid not in visible and visible:
            self.item_tree.selection_set(visible[0])
            self.item_tree.focus(visible[0])
            self._select_item()

    def _toggle_meta(self):
        if self.embedded:
            popup = tk.Toplevel(self)
            popup.title("会话详情")
            frame = ttk.Frame(popup, padding=20)
            frame.pack(fill="both", expand=True)
            text = tk.Text(frame, wrap="word", bg=COLORS["surface"], fg=COLORS["text"], font=("Helvetica Neue",12), relief="flat", width=65, height=14)
            scroll = ttk.Scrollbar(frame, command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            text.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
            text.insert("1.0", getattr(self, "detail_text", "尚未选择会话"));text.configure(state="disabled")
            return
        self.details_visible = not self.details_visible
        self.meta_label.configure(text=getattr(self, "detail_text", "") if self.details_visible else getattr(self, "summary_text", ""))

    def _empty_preview(self, text="此分类没有会话。请选择其他分类或重新检查。"):
        self._cancel_preview_loading()
        self.preview_generation += 1
        self.current_item = None
        self.current_item_iid = ""
        self.detail_text = self.summary_text = "尚未选择会话"
        self.current_versions = {}
        self.version_combo["values"] = ()
        self.version_var.set("")
        self.title_error.configure(text="")
        self.item_tree.selection_remove(*self.item_tree.selection())
        self.title_var.set("")
        self.title_entry.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.meta_label.configure(text="尚未选择会话")
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("end", text, "notice")
        self.preview_text.configure(state="disabled")
        self.preview_status.configure(text="0 条")

    def _sort_by_time(self, *, toggle: bool = True) -> None:
        if toggle:
            self.time_descending = not self.time_descending
        rows = sorted_activity_ids(self.item_tree.get_children(), self.activity_times,
                                   descending=self.time_descending)
        for position, iid in enumerate(rows):
            self.item_tree.move(iid, "", position)
        self.item_tree.heading("time", text="最后活动 " + ("↓" if self.time_descending else "↑"))
        selected = self.item_tree.selection()
        if selected:
            self.item_tree.see(selected[0])

    def _initial_title(self, item: ImportItem) -> str:
        if item.action == "skipped-existing":
            return item.local_title
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
        if self.embedded:
            self.title_error.grid_remove()
        editable = bool(item.task_id) and item.action not in ("skipped-existing", "skipped-time")
        self.title_entry.configure(state="normal" if editable else "disabled")
        self.save_button.configure(state="normal" if editable else "disabled")
        self._loading_item = False

        source_title = item.source_title or "无"
        local_title = item.local_title or "无"
        detail = item.detail or "无"
        self.summary_text = f"{project_label(item.project)} · {format_activity(self.activity_times[next_iid])}"
        self.detail_text = (
            f"Task ID：{item.task_id or '不可用'}\n来源标题：{source_title}\n本机标题：{local_title}\n"
            f"来源项目：{project_detail(item.project)}\n最后活动（北京时间）：{format_activity(self.activity_times[next_iid])}\n"
            f"文件：{item.relative_path}\n说明：{detail}"
        )
        self.meta_label.configure(text=self.detail_text if self.details_visible else self.summary_text)
        versions = preview_sources(item)
        self.current_versions = {source.label: source for source in versions}
        labels = [source.label for source in versions]
        self.version_combo["values"] = labels
        self.version_var.set(labels[0])
        if self.embedded:
            if len(labels) <= 1:
                self.version_combo.pack_forget()
                self.version_label.pack_forget()
            else:
                self.version_combo.pack(side="right")
                self.version_label.pack(side="right")
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
        dialogue = self.preview_mode.get() == "对话模式"
        self.preview_text.configure(font=("TkDefaultFont", 11) if dialogue else ("TkFixedFont", 10))
        self.preview_iterator = iter_dialogue(source) if dialogue else source.iter_records()
        self.preview_status.configure(text="正在加载…")
        self._append_preview_batch(generation)

    def _append_preview_batch(self, generation: int) -> None:
        if generation != self.preview_generation or self.preview_iterator is None:
            return
        self.preview_text.configure(state="normal")
        appended = 0
        appended_bytes = 0
        try:
            while appended < 40 and appended_bytes < 128 * 1024:
                record = next(self.preview_iterator)
                if self.preview_record_count:
                    self.preview_text.insert("end", "\n\n")
                if isinstance(record, DialogueMessage):
                    role = record.role
                    if role == "notice":
                        self.preview_text.insert("end", record.text, "notice")
                    else:
                        label = "你" if role == "user" else "助手"
                        timestamp = record.timestamp.replace("T", " ").replace("Z", " UTC")
                        self.preview_text.insert("end", label + ("  ·  " + timestamp if timestamp else "") + "\n", role + "_header")
                        self.preview_text.insert("end", record.text + "\n", role + "_body")
                    byte_count = len(record.text.encode("utf-8", errors="replace"))
                else:
                    self.preview_text.insert("end", record)
                    byte_count = len(record.encode("utf-8", errors="replace"))
                self.preview_record_count += 1
                appended += 1
                appended_bytes += byte_count
        except StopIteration:
            self.preview_iterator = None
            self.preview_text.configure(state="disabled")
            self.preview_status.configure(text=f"{'对话' if self.preview_mode.get() == '对话模式' else '记录'} · {self.preview_record_count} 条")
            self.preview_text.yview_moveto(0)
            return
        self.preview_text.configure(state="disabled")
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
        if item is None or not item.task_id or item.action in ("skipped-existing", "skipped-time"):
            return True
        if not self.title_var.get().strip() and not self._initial_title(item):
            if show_feedback:
                self.title_error.grid()
                self.title_error.configure(text="标题不能为空。", foreground=COLORS["danger"])
                self.title_entry.focus_set()
                return False
            return True
        try:
            title = normalize_title(self.title_var.get())
        except ValueError as exc:
            self.title_error.grid()
            self.title_error.configure(text=str(exc), foreground=COLORS["danger"])
            self.title_entry.focus_set()
            return False
        self.title_var.set(title)
        if title != self._initial_title(item):
            self.on_title_saved(item.task_id, title)
        if self.current_item_iid:
            self.item_tree.set(self.current_item_iid, "title", title)
        feedback = "已保存，导入时应用" if show_feedback else ""
        if self.embedded:
            self.title_error.grid() if feedback else self.title_error.grid_remove()
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


class ImportPreviewPane(ttk.Frame):
    """Persistent list and conversation preview, sharing the dialog's verified behavior."""
    def __init__(self, parent, plan, category, title_overrides, on_title_saved):
        super().__init__(parent)
        self.plan, self.category = plan, category
        self.items = items_for_category(plan, category)
        self.activity_times = {str(index): preview_activity(item) for index, item in enumerate(self.items)}
        self.project_ids = {str(index): normalize_project(item.project)["group_id"] for index, item in enumerate(self.items)}
        groups = {}
        for item in self.items:
            project = normalize_project(item.project)
            group = groups.setdefault(project["group_id"], {"project": project, "count": 0})
            group["count"] += 1
        labels = [project_label(group["project"]) for group in groups.values()]
        self.project_choices = {"全部项目": None}
        for identity, group in sorted(groups.items(), key=lambda pair: project_label(pair[1]["project"])):
            label = project_label(group["project"])
            if labels.count(label) > 1:
                label += " · " + identity[-8:]
            self.project_choices[f"{label}（{group['count']}）"] = identity
        self.last_project_choice = "全部项目"
        self.time_descending = True
        self.title_overrides, self.on_title_saved = title_overrides, on_title_saved
        self.current_item = None
        self.current_item_iid = ""
        self.current_versions = {}
        self.preview_iterator = None
        self.preview_generation = self.preview_record_count = 0
        self._loading_item = False
        self.embedded = True
        self.details_visible = False
        self._build_ui(CATEGORY_TITLES.get(category, "会话"))
        if self.items:
            first = self.item_tree.get_children()[0]
            self.item_tree.selection_set(first)
            self.item_tree.focus(first)
            self._select_item()
        else:
            self._empty_preview()

    def _close(self):
        self._commit_title(show_feedback=True)

    def destroy(self):
        self._cancel_preview_loading()
        self.preview_generation += 1
        super().destroy()


for _name in ("_build_ui", "_initial_title", "_select_item", "_show_version", "_append_preview_batch",
              "_cancel_preview_loading", "_validate_title", "_save_title", "_commit_title", "_filter_project",
              "_sort_by_time", "_toggle_meta", "_empty_preview"):
    setattr(ImportPreviewPane, _name, getattr(ImportPreviewDialog, _name))
