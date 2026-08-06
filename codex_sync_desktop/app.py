from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from . import __version__
from .core.backups import (
    clear_backup_storage,
    create_import_transaction,
    finish_import_transaction,
    latest_reversible_transaction,
    list_backup_records,
    prune_backup_history,
    rollback_import_transaction,
)
from .core.config import SettingsStore, device_slug
from .core.config_health import repair_model_provider_to_openai
from .core.diagnostics import collect_diagnostics, diagnostics_json, remediation_text, session_index_summary
from .core.git_client import VaultGit, compact_failure_reason, summarize_pull
from .core.import_preview import apply_title_overrides, items_for_category
from .core.index_repair import repair_indexes
from .core.onboarding import validate_proxy_url
from .core.processes import running_codex_processes
from .core.sessions import apply_import, export_sanitized_sessions, list_source_device_options, plan_import
from .import_preview_dialog import ImportPreviewDialog
from .ui_theme import COLORS, center_window
from .window_chrome import WindowChrome, configure_windows_app_identity
from .wizard import OnboardingWizard


class QueueLogHandler(logging.Handler):
    def __init__(self, messages: queue.Queue):
        super().__init__()
        self.messages = messages

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.put(("log", self.format(record)))


def dependency_setup_incomplete(diagnostics: dict[str, Any]) -> bool:
    return not bool(diagnostics.get("git")) or not bool(diagnostics.get("gh"))


class CodexSyncApp(tk.Tk):
    def __init__(self, store: SettingsStore | None = None):
        super().__init__()
        self.store = store or SettingsStore()
        self.settings = self.store.load()
        self.messages: queue.Queue = queue.Queue()
        self.active_plan = None
        self.title_overrides: dict[str, dict[str, str]] = {}
        self.source_device_keys: dict[str, str] = {}
        self.last_diagnostics: dict[str, Any] | None = None
        self.task_buttons: list[ttk.Button] = []
        self.pages: dict[str, ttk.Frame] = {}
        self.nav_buttons: dict[str, ttk.Button] = {}
        self._busy = False
        self._dependency_prompted = False
        self._config_prompted = False
        self.title(f"Codex Sync Desktop {__version__}")
        self.geometry("1120x760")
        self.minsize(920, 640)
        self.configure(background=COLORS["background"])
        self.chrome = WindowChrome(self, f"Codex Sync Desktop  {__version__}", self.destroy)
        self._configure_logging()
        self._configure_styles()
        self._build_ui()
        self.after(120, self._poll_messages)
        self.after(250, self.refresh_all)
        self.after(700, self.maybe_show_onboarding)

    def report_callback_exception(self, exc_type: type[BaseException], exc: BaseException, trace: Any) -> None:
        self.logger.error("界面操作失败：%s", exc, exc_info=(exc_type, exc, trace))
        self._set_status_text("失败", failed=True)
        messagebox.showerror("界面操作失败", str(exc))

    def _configure_logging(self) -> None:
        app_home = self.store.app_home
        app_home.mkdir(parents=True, exist_ok=True)
        log_path = app_home / "codex-sync.log"
        formatter = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%Y-%m-%d %H:%M:%S")
        logger = logging.getLogger("codex_sync_desktop")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        queue_handler = QueueLogHandler(self.messages)
        queue_handler.setFormatter(formatter)
        file_handler = RotatingFileHandler(log_path, maxBytes=1024 * 1024, backupCount=1, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(queue_handler)
        logger.addHandler(file_handler)
        self.logger = logger
        self.log_file_handler = file_handler

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        body_font = ("Segoe UI", 10) if os.name == "nt" else ("Helvetica Neue", 12)
        heading_font = ("Cascadia Code SemiBold", 19) if os.name == "nt" else ("SF Mono", 20, "bold")
        section_font = ("Cascadia Code SemiBold", 11) if os.name == "nt" else ("SF Mono", 13, "bold")
        self.option_add("*Font", body_font)
        style.configure("TFrame", background=COLORS["background"])
        style.configure("Panel.TFrame", background=COLORS["surface"])
        style.configure("Sidebar.TFrame", background=COLORS["sidebar"])
        style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"], font=body_font)
        style.configure("Panel.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=body_font)
        style.configure("Title.TLabel", font=heading_font, background=COLORS["background"], foreground=COLORS["text"])
        style.configure("Section.TLabel", font=section_font, background=COLORS["background"], foreground=COLORS["cyan"])
        style.configure("PanelSection.TLabel", font=section_font, background=COLORS["surface"], foreground=COLORS["cyan"])
        style.configure("Muted.TLabel", foreground=COLORS["text_muted"], background=COLORS["background"], font=body_font)
        style.configure("PanelMuted.TLabel", foreground=COLORS["text_muted"], background=COLORS["surface"], font=body_font)
        style.configure("Activity.TLabel", foreground=COLORS["primary"], background=COLORS["background"], font=body_font)
        style.configure("ActivityError.TLabel", foreground=COLORS["danger"], background=COLORS["background"], font=body_font)
        style.configure("SidebarTitle.TLabel", foreground=COLORS["text"], background=COLORS["sidebar"], font=section_font)
        style.configure("SidebarMuted.TLabel", foreground=COLORS["cyan"], background=COLORS["sidebar"], font=body_font)
        style.configure("Status.TLabel", foreground=COLORS["primary"], background=COLORS["surface_alt"], padding=(12, 7), font=body_font)
        style.configure("Error.Status.TLabel", foreground=COLORS["danger"], background=COLORS["surface_alt"], padding=(12, 7), font=body_font)
        style.configure("Status.TEntry", foreground=COLORS["primary"], fieldbackground=COLORS["surface_alt"], bordercolor=COLORS["border"], padding=(12, 7), font=body_font)
        style.map("Status.TEntry", foreground=[("readonly", COLORS["primary"])], fieldbackground=[("readonly", COLORS["surface_alt"])], bordercolor=[("focus", COLORS["border"])])
        style.configure("Error.Status.TEntry", foreground=COLORS["danger"], fieldbackground=COLORS["surface_alt"], bordercolor=COLORS["danger"], padding=(12, 7), font=body_font)
        style.map("Error.Status.TEntry", foreground=[("readonly", COLORS["danger"])], fieldbackground=[("readonly", COLORS["surface_alt"])])
        style.configure("Status.Horizontal.TScrollbar", background=COLORS["secondary"], troughcolor=COLORS["surface_alt"], arrowcolor=COLORS["cyan"], bordercolor=COLORS["border"])
        style.map("Status.Horizontal.TScrollbar", background=[("active", COLORS["primary"]), ("pressed", COLORS["primary_pressed"])])
        style.configure("TButton", foreground=COLORS["text"], background=COLORS["secondary"], padding=(12, 8), borderwidth=1, font=body_font)
        style.map("TButton", background=[("disabled", COLORS["button_disabled"]), ("pressed", COLORS["secondary_pressed"]), ("active", COLORS["secondary_hover"])], foreground=[("disabled", COLORS["text_disabled"]), ("!disabled", COLORS["text"])])
        style.configure("Accent.TButton", foreground=COLORS["background"], background=COLORS["primary"], padding=(14, 9), borderwidth=1, font=body_font)
        style.map("Accent.TButton", background=[("disabled", COLORS["button_disabled"]), ("pressed", COLORS["primary_pressed"]), ("active", COLORS["primary_hover"])], foreground=[("disabled", COLORS["text_disabled"]), ("!disabled", COLORS["background"])])
        style.configure("Danger.TButton", foreground=COLORS["text"], background=COLORS["danger"], padding=(14, 9), borderwidth=1, font=body_font)
        style.map("Danger.TButton", background=[("disabled", COLORS["button_disabled"]), ("active", COLORS["danger_hover"])], foreground=[("disabled", COLORS["text_disabled"])])
        style.configure("Nav.TButton", foreground=COLORS["text_muted"], background=COLORS["sidebar"], anchor="w", padding=(18, 12), borderwidth=0, font=body_font)
        style.map("Nav.TButton", background=[("active", COLORS["surface_alt"])], foreground=[("active", COLORS["text"])])
        style.configure("NavActive.TButton", foreground=COLORS["background"], background=COLORS["primary"], anchor="w", padding=(18, 12), borderwidth=0, font=body_font)
        style.configure("TEntry", fieldbackground=COLORS["surface_alt"], foreground=COLORS["text"], insertcolor=COLORS["primary"], bordercolor=COLORS["border"], padding=(8, 7), font=body_font)
        style.map("TEntry", bordercolor=[("focus", COLORS["cyan"])], lightcolor=[("focus", COLORS["cyan"])], darkcolor=[("focus", COLORS["cyan"])])
        style.configure("TCombobox", fieldbackground=COLORS["surface_alt"], background=COLORS["secondary"], foreground=COLORS["text"], arrowcolor=COLORS["text"], bordercolor=COLORS["border"], padding=(8, 7), font=body_font)
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["surface_alt"])], selectbackground=[("readonly", COLORS["surface_alt"])], selectforeground=[("readonly", COLORS["text"])])
        style.configure("TCheckbutton", background=COLORS["surface"], foreground=COLORS["text"], indicatorcolor=COLORS["surface_alt"], font=body_font)
        style.map("TCheckbutton", background=[("active", COLORS["surface"])], foreground=[("disabled", COLORS["text_disabled"])], indicatorcolor=[("selected", COLORS["primary"])])
        style.layout(
            "Checkmark.TCheckbutton",
            [("Checkbutton.padding", {"sticky": "nswe", "children": [("Checkbutton.label", {"sticky": "nswe"})]})],
        )
        style.configure(
            "Checkmark.TCheckbutton",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            padding=(0, 4),
            font=body_font,
        )
        style.map(
            "Checkmark.TCheckbutton",
            background=[("active", COLORS["surface"])],
            foreground=[("disabled", COLORS["text_disabled"]), ("!disabled", COLORS["text"])],
        )
        style.configure("Treeview", rowheight=32, background=COLORS["surface"], fieldbackground=COLORS["surface"], foreground=COLORS["text"], bordercolor=COLORS["border"], lightcolor=COLORS["border"], darkcolor=COLORS["border"], font=body_font)
        style.map("Treeview", background=[("selected", COLORS["secondary"])], foreground=[("selected", COLORS["text"])])
        style.configure("Treeview.Heading", font=section_font, background=COLORS["surface_alt"], foreground=COLORS["cyan"], bordercolor=COLORS["border"], padding=(8, 7))
        style.map("Treeview.Heading", background=[("active", COLORS["secondary_pressed"])])
        style.configure("Vertical.TScrollbar", background=COLORS["surface_alt"], troughcolor=COLORS["background"], arrowcolor=COLORS["text_muted"], bordercolor=COLORS["border"])
        style.configure(
            "Wizard.Vertical.TScrollbar",
            background=COLORS["secondary"],
            troughcolor=COLORS["surface_alt"],
            arrowcolor=COLORS["cyan"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["secondary_hover"],
            darkcolor=COLORS["secondary_pressed"],
            relief="flat",
            borderwidth=0,
            arrowsize=14,
            width=15,
        )
        style.map(
            "Wizard.Vertical.TScrollbar",
            background=[("active", COLORS["primary"]), ("pressed", COLORS["primary_pressed"])],
            arrowcolor=[("active", COLORS["text"]), ("pressed", COLORS["text"])],
        )
        style.configure("Tech.Horizontal.TProgressbar", troughcolor=COLORS["surface_alt"], background=COLORS["primary"], lightcolor=COLORS["primary"], darkcolor=COLORS["primary"], bordercolor=COLORS["border"], thickness=8)

    def _build_ui(self) -> None:
        header = ttk.Frame(self.chrome.body, padding=(24, 16, 24, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Codex Sync Desktop", style="Title.TLabel").pack(side="left")
        status = ttk.Frame(header)
        status.pack(side="right")
        self.task_progress = ttk.Progressbar(status, mode="indeterminate", length=140, style="Tech.Horizontal.TProgressbar")
        self.task_progress.pack(side="left", padx=(0, 10))
        status_text = ttk.Frame(status)
        status_text.pack(side="left")
        self.busy_text = tk.StringVar(value="就绪")
        self.busy_label = ttk.Entry(
            status_text,
            textvariable=self.busy_text,
            state="readonly",
            style="Status.TEntry",
            width=34,
            justify="left",
            takefocus=False,
        )
        self.busy_label.pack(fill="x")
        self.busy_scroll = ttk.Scrollbar(
            status_text,
            orient="horizontal",
            command=self.busy_label.xview,
            style="Status.Horizontal.TScrollbar",
        )
        self.busy_scroll.pack(fill="x", pady=(2, 0))
        self.busy_label.configure(xscrollcommand=self.busy_scroll.set)
        shell = ttk.Frame(self.chrome.body, padding=(20, 0, 20, 20))
        shell.pack(fill="both", expand=True)
        sidebar = ttk.Frame(shell, style="Sidebar.TFrame", padding=(0, 18))
        sidebar.pack(side="left", fill="y")
        sidebar.configure(width=190)
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="同步控制台", style="SidebarTitle.TLabel", padding=(18, 0, 12, 14)).pack(fill="x")
        for key, title in (
            ("overview", "概览"),
            ("sync", "同步与导入"),
            ("backups", "备份与清理"),
            ("maintenance", "日志与设置"),
        ):
            button = ttk.Button(sidebar, text=title, style="Nav.TButton", command=lambda value=key: self.show_page(value))
            button.pack(fill="x", padx=8, pady=3)
            button.bind("<ButtonRelease-1>", self._release_nav_mouse_focus, add="+")
            self.nav_buttons[key] = button
        ttk.Label(sidebar, text=f"版本 {__version__}", style="SidebarMuted.TLabel", padding=(18, 16)).pack(side="bottom", fill="x")
        self.content = ttk.Frame(shell, padding=(18, 0, 0, 0))
        self.content.pack(side="left", fill="both", expand=True)
        for key in ("overview", "sync", "backups", "maintenance"):
            self.pages[key] = ttk.Frame(self.content)
        self.overview_tab = self.pages["overview"]
        self.sync_tab = self.pages["sync"]
        self.backups_tab = self.pages["backups"]
        self.maintenance_tab = self.pages["maintenance"]
        self._build_overview()
        self._build_sync()
        self._build_backups()
        self._build_maintenance()
        self.show_page("overview")

    def _release_nav_mouse_focus(self, _event: tk.Event) -> None:
        """Mouse selection uses the active-page fill without a dotted focus ring."""
        self.after_idle(self.chrome.body.focus_set)

    def show_page(self, name: str) -> None:
        for key, page in self.pages.items():
            page.pack_forget()
            self.nav_buttons[key].configure(style="NavActive.TButton" if key == name else "Nav.TButton")
        self.pages[name].pack(fill="both", expand=True)
        if name == "backups":
            self.refresh_backups()
        elif name == "sync":
            self.refresh_sources()

    @staticmethod
    def _page_header(parent: ttk.Frame, title: str, subtitle: str) -> None:
        ttk.Label(parent, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(parent, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(2, 14))

    def _task_button(self, parent: ttk.Frame, text: str, command: Callable[[], None], style: str = "TButton") -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command, style=style)
        self.task_buttons.append(button)
        return button

    def _build_overview(self) -> None:
        self._page_header(self.overview_tab, "运行概览", "检查本机 Codex、同步仓库和必要工具状态")
        toolbar = ttk.Frame(self.overview_tab)
        toolbar.pack(fill="x", pady=(0, 10))
        self._task_button(toolbar, "刷新检查", self.refresh_all, "Accent.TButton").pack(side="left")
        ttk.Button(toolbar, text="打开 Codex 目录", command=lambda: self._open_path(self.settings.codex_path)).pack(side="left", padx=6)
        ttk.Button(toolbar, text="首次配置向导", command=self.open_onboarding).pack(side="left", padx=6)
        self.overview_tree = self._tree(self.overview_tab, ("item", "status", "detail"), (180, 120, 590))

    def _build_sync(self) -> None:
        self._page_header(self.sync_tab, "同步与导入", "来源设备在这里选择；内容差异会在后台自动合并")
        source_panel = ttk.Frame(self.sync_tab, style="Panel.TFrame", padding=14)
        source_panel.pack(fill="x", pady=(0, 12))
        ttk.Label(source_panel, text="来源设备", style="PanelSection.TLabel").grid(row=0, column=0, sticky="w")
        self.source_device = tk.StringVar()
        self.device_combo = ttk.Combobox(source_panel, textvariable=self.source_device, state="readonly", width=30)
        self.device_combo.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.device_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_source_summary())
        self.source_count_label = ttk.Label(source_panel, text="会话数量：—", style="Panel.TLabel")
        self.source_count_label.grid(row=0, column=1, rowspan=2, sticky="w", padx=(24, 10))
        self.source_time_label = ttk.Label(source_panel, text="最后上传：—", style="PanelMuted.TLabel")
        self.source_time_label.grid(row=0, column=2, rowspan=2, sticky="w", padx=(10, 0))
        source_panel.columnconfigure(0, weight=1)
        actions = ttk.Frame(self.sync_tab)
        actions.pack(fill="x", pady=(0, 12))
        self._task_button(actions, "一键同步", self.sync_once, "Accent.TButton").pack(side="left")
        self._task_button(actions, "拉取仓库", self.pull_vault).pack(side="left", padx=6)
        self._task_button(actions, "导出并推送", self.export_and_push).pack(side="left", padx=6)
        self._task_button(actions, "预览导入", self.preview_import).pack(side="left", padx=(12, 6))
        self._task_button(actions, "导入并修复", self.import_and_repair).pack(side="left")
        ttk.Label(
            self.sync_tab,
            text="拉取、导出和预览无需退出 ChatGPT/Codex；导入修复、包含导入的一键同步和撤销前需要退出。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        self.import_tree = self._tree(self.sync_tab, ("action", "count", "meaning"), (180, 100, 610))
        self.import_tree.bind("<ButtonRelease-1>", self._open_import_action_from_event, add="+")
        self.import_tree.bind("<Return>", lambda _event: self._open_selected_import_action(), add="+")

    def _build_backups(self) -> None:
        self._page_header(self.backups_tab, "备份与清理", "仅保留最近一次导入保护；撤销前会校验会话是否被继续修改")
        toolbar = ttk.Frame(self.backups_tab)
        toolbar.pack(fill="x", pady=(0, 10))
        self._task_button(toolbar, "撤销最近一次导入", self.undo_latest_import, "Danger.TButton").pack(side="left")
        self._task_button(toolbar, "一键清理所有备份", self.clear_backups).pack(side="left", padx=6)
        ttk.Button(toolbar, text="打开备份目录", command=lambda: self._open_path(self.settings.codex_path / "sync-backups")).pack(side="left")
        ttk.Button(toolbar, text="刷新", command=self.refresh_backups).pack(side="left", padx=6)
        self.backup_summary = ttk.Label(self.backups_tab, text="当前无备份", style="Muted.TLabel")
        self.backup_summary.pack(anchor="w", pady=(0, 8))
        self.backup_tree = self._tree(self.backups_tab, ("created", "kind", "status", "files", "size", "detail"), (180, 110, 100, 80, 90, 260))

    def _build_maintenance(self) -> None:
        self._page_header(self.maintenance_tab, "日志与设置", "日志自动限制为约 2 MiB；项目路径保持原始值，不做映射")
        panel = ttk.Frame(self.maintenance_tab, style="Panel.TFrame", padding=16)
        panel.pack(fill="x", pady=(0, 14))
        self.setting_vars = {
            "codex_home": tk.StringVar(value=self.settings.codex_home),
            "vault_path": tk.StringVar(value=self.settings.vault_path),
            "vault_remote": tk.StringVar(value=self.settings.vault_remote),
            "device_name": tk.StringVar(value=self.settings.device_name),
            "proxy_url": tk.StringVar(value=self.settings.proxy_url),
        }
        ttk.Label(panel, text="同步设置", style="PanelSection.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        labels = (("codex_home", "Codex 数据目录"), ("vault_path", "本地同步仓库"), ("vault_remote", "GitHub 仓库地址"), ("device_name", "设备名称"), ("proxy_url", "HTTP 代理（可选）"))
        for row, (key, label) in enumerate(labels):
            grid_row = row + 1
            ttk.Label(panel, text=label, style="Panel.TLabel", width=16).grid(row=grid_row, column=0, sticky="w", pady=5)
            ttk.Entry(panel, textvariable=self.setting_vars[key]).grid(row=grid_row, column=1, sticky="ew", pady=5)
            if key in ("codex_home", "vault_path"):
                ttk.Button(panel, text="选择", command=lambda k=key: self.choose_directory(k)).grid(row=grid_row, column=2, padx=(8, 0))
        panel.columnconfigure(1, weight=1)
        buttons = ttk.Frame(panel, style="Panel.TFrame")
        buttons.grid(row=len(labels) + 1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self._task_button(buttons, "保存设置", self.save_settings, "Accent.TButton").pack(side="left")
        logs_header = ttk.Frame(self.maintenance_tab)
        logs_header.pack(fill="x", pady=(0, 8))
        ttk.Label(logs_header, text="运行日志", style="Section.TLabel").pack(side="left")
        ttk.Button(logs_header, text="打开日志文件", command=lambda: self._open_path(self.store.app_home / "codex-sync.log")).pack(side="right")
        self._task_button(logs_header, "一键清理日志", self.clear_logs).pack(side="right", padx=6)
        self.log_text = tk.Text(self.maintenance_tab, wrap="word", borderwidth=1, relief="solid", font=("TkFixedFont", 10), background=COLORS["surface"], foreground=COLORS["primary"], insertbackground=COLORS["primary"], highlightbackground=COLORS["border"], highlightcolor=COLORS["cyan"], padx=10, pady=10)
        self.log_text.pack(fill="both", expand=True)

    def _tree(self, parent: ttk.Frame, columns: tuple[str, ...], widths: tuple[int, ...]) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        titles = {"item": "检查项", "status": "状态", "detail": "详情", "action": "动作", "count": "数量", "meaning": "说明", "created": "创建时间", "kind": "类型", "files": "文件数", "size": "占用空间"}
        for column, width in zip(columns, widths):
            tree.heading(column, text=titles.get(column, column))
            tree.column(column, width=width, minwidth=70, stretch=True)
        return tree

    def refresh_all(self) -> None:
        self.overview_tree.delete(*self.overview_tree.get_children())
        self.overview_tree.insert("", "end", values=("环境检查", "检查中", "正在读取 Codex 和 Git 环境"))
        self._run_task(
            "刷新检查",
            lambda: collect_diagnostics(self.settings.codex_path, self.settings.vault, self.settings.proxy_url),
            self._show_overview,
            callback_with_result=True,
        )

    def _show_overview(self, diagnostics: dict[str, Any]) -> None:
        self.last_diagnostics = diagnostics
        self.overview_tree.delete(*self.overview_tree.get_children())
        lfs_required = diagnostics.get("git_lfs_required", False)
        lfs_status = "正常" if diagnostics["git_lfs"] else ("缺失（必需）" if lfs_required else "未安装（可选）")
        lfs_detail = "Git LFS 可用" if diagnostics["git_lfs"] else (
            "请在首次配置向导中安装 Git LFS" if lfs_required else "当前仓库未检测到 LFS，可以不处理"
        )
        if diagnostics.get("gh_authenticated"):
            gh_status, gh_detail = "已登录", "认证可用"
        elif diagnostics.get("gh"):
            gh_status, gh_detail = "未登录（可选）", "执行 gh auth login；Git 能同步时可不处理"
        else:
            gh_status, gh_detail = "未安装（可选）", "Git 能同步时可不安装；也可通过首次配置向导安装"
        git_detail = "Git 可用" if diagnostics["git"] else "同步必需；请打开首次配置向导自动安装"
        codex_detail = diagnostics["codex_home"] if diagnostics["codex_home_exists"] else "在“日志与设置”中选择当前用户的 .codex 目录"
        database_detail = ", ".join(Path(item).name for item in diagnostics["databases"]) or "先启动一次 Codex，再刷新检查"
        index_status, index_detail = session_index_summary(diagnostics)
        provider_valid = bool(diagnostics.get("model_provider_config_valid", True))
        provider_status = "正常" if provider_valid else "配置错误"
        provider_detail = str(diagnostics.get("model_provider_config_reason") or "使用默认 openai")
        vault_detail = str(self.settings.vault or "") if diagnostics.get("vault_exists") else "在“日志与设置”中选择或克隆同步仓库"
        rows = [
            ("Codex 数据目录", "正常" if diagnostics["codex_home_exists"] else "未找到", codex_detail),
            ("本机会话", str(diagnostics["sessions"]), "JSONL 会话文件"),
            ("状态数据库", str(len(diagnostics["databases"])), database_detail),
            ("侧栏索引", index_status, index_detail),
            ("模型供应商配置", provider_status, provider_detail),
            ("Git", "正常" if diagnostics["git"] else "缺失（必需）", git_detail),
            ("Git LFS", lfs_status, lfs_detail),
            ("GitHub CLI", gh_status, gh_detail),
            ("相关进程", str(len(diagnostics["running_processes"])), ", ".join(item["name"] for item in diagnostics["running_processes"]) or "未检测到"),
            ("同步仓库", "正常" if diagnostics.get("vault_exists") else "未配置", vault_detail),
        ]
        for row in rows:
            self.overview_tree.insert("", "end", values=row)
        if not provider_valid and not self._config_prompted:
            self._config_prompted = True
            self.after_idle(lambda: self._offer_model_provider_repair(diagnostics))
        if (
            self.settings.onboarding_complete
            and not self._dependency_prompted
            and dependency_setup_incomplete(diagnostics)
        ):
            self._dependency_prompted = True
            self.after_idle(lambda: self.open_onboarding(initial_step=2))
        for label, refresh in (("来源设备", self.refresh_sources), ("备份", self.refresh_backups)):
            try:
                refresh()
            except Exception:
                self.logger.exception("刷新%s失败", label)

    def _offer_model_provider_repair(self, diagnostics: dict[str, Any]) -> None:
        reason = str(diagnostics.get("model_provider_config_reason") or "config.toml 模型供应商无效")
        selected = str(diagnostics.get("model_provider") or "")
        message = (
            f"检测到 Codex 无法加载模型供应商配置：\n\n{reason}\n\n"
            "这会导致已导入会话能被搜索到，但打开后无法继续，也不会进入最近会话。\n\n"
            f"是否将顶层 model_provider 从 {selected or '无效值'} 切换为内置 openai？\n"
            "软件会先备份 config.toml，不会修改 Token、代理或其他供应商定义。"
        )
        if not messagebox.askyesno("修复 Codex 模型配置", message):
            return
        try:
            backup = repair_model_provider_to_openai(self.settings.codex_path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("修复失败", str(exc))
            return
        messagebox.showinfo(
            "修复完成",
            f"已切换到内置 openai。\n备份：{backup}\n\n请完全退出并重新打开 ChatGPT/Codex，再从搜索结果打开该会话。",
        )
        self.refresh_all()

    def show_remediation(self) -> None:
        diagnostics = self.last_diagnostics or {
            "platform": "Windows" if os.name == "nt" else sys.platform,
            "codex_home_exists": self.settings.codex_path.exists(),
            "databases": [],
            "session_index": False,
            "git": False,
            "git_lfs": False,
            "git_lfs_required": False,
            "gh": False,
            "gh_authenticated": False,
            "vault_exists": bool(self.settings.vault and self.settings.vault.exists()),
        }
        content = remediation_text(diagnostics)
        dialog = tk.Toplevel(self)
        dialog.title("环境缺失项解决办法")
        dialog.configure(background=COLORS["background"])
        dialog.minsize(620, 420)
        dialog.transient(self)
        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        text = tk.Text(body, wrap="word", font=("TkFixedFont", 10), background=COLORS["surface"], foreground=COLORS["text"], insertbackground=COLORS["primary"], highlightbackground=COLORS["border"], padx=10, pady=10)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        text.insert("1.0", content)
        text.configure(state="disabled")
        buttons = ttk.Frame(dialog, padding=(14, 0, 14, 14))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="复制全部命令", command=lambda: self._copy_text(content)).pack(side="left")
        ttk.Button(buttons, text="关闭", command=dialog.destroy).pack(side="right")
        center_window(dialog, self, 780, 520)
        dialog.lift(self)
        dialog.focus_force()

    def _copy_text(self, content: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(content)
        self.update_idletasks()
        self._set_status_text("已复制")

    def refresh_sources(self) -> None:
        vault = self.settings.vault
        options = list_source_device_options(vault) if vault else []
        previous_key = CodexSyncApp._selected_source_device(self)
        self.source_device_keys = dict(options)
        labels = [label for label, _key in options]
        self.device_combo["values"] = labels
        selected = next((label for label, key in options if key == previous_key), "")
        if not selected and options:
            local_device = device_slug(self.settings.device_name)
            selected = next((label for label, key in options if key != local_device), options[0][0])
        self.source_device.set(selected)
        if not options:
            self.source_device.set("")
        self._update_source_summary()

    def _selected_source_device(self) -> str:
        selected = self.source_device.get().strip()
        return getattr(self, "source_device_keys", {}).get(selected, selected)

    def _update_source_summary(self) -> None:
        vault = self.settings.vault
        source = CodexSyncApp._selected_source_device(self)
        if not vault or not source:
            self.source_count_label.configure(text="会话数量：—")
            self.source_time_label.configure(text="最后上传：—")
            return
        manifest_path = vault / "sessions-text" / "devices" / source / "manifest.json"
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            count = len(data.get("sessions") or [])
            exported = str(data.get("exported_at") or "未知")
            self.source_count_label.configure(text=f"会话数量：{count}")
            self.source_time_label.configure(text=f"最后上传：{exported[:19].replace('T', ' ')}")
        except (OSError, ValueError, TypeError):
            self.source_count_label.configure(text="会话数量：读取失败")
            self.source_time_label.configure(text="最后上传：清单无效")

    def refresh_backups(self) -> None:
        self.backup_tree.delete(*self.backup_tree.get_children())
        records = list_backup_records(self.settings.codex_path)
        total = sum(int(record["bytes"]) for record in records)
        status_names = {"completed": "可撤销", "prepared": "未完成", "failed": "导入失败", "rolled_back": "已撤销", "invalid": "无效", "available": "可用"}
        for record in records:
            detail = f"新增 {record['copied']}，合并 {record['merged']}" if record["kind"] == "完整导入" else str(record["path"])
            self.backup_tree.insert("", "end", iid=str(record["path"]), values=(
                record["created"], record["kind"], status_names.get(str(record["status"]), str(record["status"])),
                record["files"], self._format_bytes(int(record["bytes"])), detail,
            ))
        self.backup_summary.configure(text=f"备份 {len(records)} 份，共 {self._format_bytes(total)}" if records else "当前无备份")

    def save_settings(self) -> None:
        try:
            self._save_settings_values()
        except ValueError as exc:
            messagebox.showerror("设置错误", str(exc))
            return
        self.refresh_all()

    def _save_settings_values(self) -> None:
        for key, variable in self.setting_vars.items():
            setattr(self.settings, key, variable.get().strip())
        self.settings.proxy_url = validate_proxy_url(self.settings.proxy_url)
        if self.settings.vault_path:
            self.settings.onboarding_complete = True
        self.store.save(self.settings)
        self.logger.info("设置已保存")

    def choose_directory(self, key: str) -> None:
        selected = filedialog.askdirectory(initialdir=self.setting_vars[key].get() or str(Path.home()))
        if selected:
            self.setting_vars[key].set(selected)

    def prepare_vault(self) -> None:
        try:
            self._save_settings_values()
        except ValueError as exc:
            messagebox.showerror("设置错误", str(exc))
            return
        vault = self.settings.vault
        if not vault:
            messagebox.showwarning("未配置仓库", "请先选择本地同步仓库。")
            return
        def work() -> Any:
            self._report_progress("正在初始化或克隆同步仓库")
            return VaultGit(vault, self.settings.vault_remote, self.settings.proxy_url).prepare()
        self._run_task("初始化仓库", work, self.refresh_all)

    def pull_vault(self) -> None:
        vault = self._require_vault()
        if vault:
            def work() -> str:
                self._report_progress("正在从 GitHub 拉取仓库")
                result = VaultGit(vault, proxy_url=self.settings.proxy_url).pull()
                if result.output:
                    self.logger.info("Git pull 完整输出：\n%s", result.output)
                self._checked_git(result)
                return summarize_pull(result.output)
            self._run_task("拉取仓库", work, self.refresh_sources)

    def export_and_push(self) -> None:
        vault = self._require_vault()
        if not vault:
            return
        self._run_task("导出并推送", lambda: self._export_and_push_work(vault), self.refresh_sources)

    def _export_and_push_work(self, vault: Path, force_push: bool = False) -> str:
        self._report_progress("正在整理并导出本机活动会话")
        report = export_sanitized_sessions(self.settings.codex_path, vault, self.settings.device_name)
        self.logger.info(
            "已导出 %s 个活动文字会话，移除 %s 个不再同步的旧副本和 %s 个媒体或二进制块",
            report.sessions,
            report.removed_files,
            report.media_removed,
        )
        if force_push or self.settings.auto_push_after_export:
            self._report_progress("正在提交并推送到 GitHub")
            result = VaultGit(vault, proxy_url=self.settings.proxy_url).commit_and_push(
                f"sync: update {device_slug(self.settings.device_name)}"
            )
            self._checked_git(result)
        return f"结果：成功\n活动会话：{report.sessions}\n停止同步：{report.removed_files}\n失败：0"

    def sync_once(self) -> None:
        vault = self._require_vault()
        if not vault:
            return
        source = CodexSyncApp._selected_source_device(self)
        source_label = self.source_device.get().strip() or source
        local_device = device_slug(self.settings.device_name)
        should_import = bool(source and source != local_device)
        if should_import:
            processes = running_codex_processes(os.getpid())
            if processes:
                names = ", ".join(f"{item.name} (PID {item.pid})" for item in processes)
                messagebox.showerror("需要退出相关程序", f"一键同步包含导入和索引修复，请先退出 Codex、ChatGPT 和 Codex++。\n\n检测到：{names}")
                return
        description = "拉取仓库并上传本机活动会话"
        if should_import:
            description = f"拉取仓库、导入来源设备 {source_label}、修复侧栏，再上传本机活动会话"
        if not messagebox.askyesno("确认一键同步", description + "。是否继续？"):
            return

        def work() -> str:
            git = VaultGit(vault, proxy_url=self.settings.proxy_url)
            self._report_progress("正在从 GitHub 拉取最新内容")
            self._checked_git(git.pull())
            copied = merged = titles = 0
            if should_import:
                self._report_progress(f"正在分析来源设备 {source_label} 的会话")
                plan = plan_import(self.settings.codex_path, vault, source)
                CodexSyncApp._apply_preview_title_overrides(self, plan)
                has_changes = any(item.action in ("copy", "conflict") for item in plan.items) or bool(plan.title_updates)
                if has_changes:
                    transaction = create_import_transaction(self.settings.codex_path, plan)
                    try:
                        self._report_progress("正在合并会话内容")
                        result = apply_import(plan)
                        self._report_progress("正在修复标题和侧栏索引")
                        repair_indexes(self.settings.codex_path, {}, create_backup=False, preferred_titles=plan.title_updates)
                        finish_import_transaction(transaction, result["counts"])
                        prune_backup_history(self.settings.codex_path, keep=1)
                    except Exception:
                        finish_import_transaction(transaction, plan.counts, status="failed")
                        raise
                    copied = len(result["copied"])
                    merged = len(result["merged"])
                    titles = len(plan.title_updates)
                else:
                    # A previous interrupted import may have copied files before its index repair failed.
                    self._report_progress("正在校验并修复侧栏索引")
                    repair_indexes(
                        self.settings.codex_path,
                        {},
                        create_backup=True,
                        preferred_titles=plan.title_updates,
                    )
                    prune_backup_history(self.settings.codex_path, keep=1)
            self._report_progress("正在导出本机活动会话")
            report = export_sanitized_sessions(self.settings.codex_path, vault, self.settings.device_name)
            self._report_progress("正在提交并推送到 GitHub")
            self._checked_git(git.commit_and_push(f"sync: one-click update {local_device}"))
            return (
                "结果：成功\n"
                f"导入新增：{copied}\n"
                f"自动合并：{merged}\n"
                f"标题更新：{titles}\n"
                f"上传活动会话：{report.sessions}\n"
                f"停止同步：{report.removed_files}\n"
                "失败：0"
            )

        self._run_task("一键同步", work, self.refresh_all)

    def preview_import(self) -> None:
        vault = self._require_vault()
        source = CodexSyncApp._selected_source_device(self)
        source_label = self.source_device.get().strip() or source
        if not vault or not source:
            messagebox.showwarning("缺少来源", "请选择来源设备。")
            return
        def work() -> Any:
            if self.settings.auto_pull_before_import:
                self._report_progress("正在拉取仓库最新内容")
                self._checked_git(VaultGit(vault, proxy_url=self.settings.proxy_url).pull())
            self._report_progress(f"正在分析来源设备 {source_label} 的会话")
            plan = plan_import(self.settings.codex_path, vault, source)
            CodexSyncApp._apply_preview_title_overrides(self, plan)
            return plan
        self._run_task("预览导入", work, self._show_import_plan, callback_with_result=True)

    def import_and_repair(self) -> None:
        vault = self._require_vault()
        source = CodexSyncApp._selected_source_device(self)
        source_label = self.source_device.get().strip() or source
        if not vault or not source:
            messagebox.showwarning("缺少来源", "请选择来源设备。")
            return
        processes = running_codex_processes(os.getpid())
        if processes:
            names = ", ".join(f"{item.name} (PID {item.pid})" for item in processes)
            messagebox.showerror("需要退出相关程序", f"修复数据库前请退出 Codex、ChatGPT 和 Codex++。\n\n检测到：{names}")
            return
        if not messagebox.askyesno("确认导入", "将保留一次完整撤销点、追加新会话，并按内容和时间自动合并差异后重建侧栏索引。是否继续？"):
            return
        def work() -> str:
            if self.settings.auto_pull_before_import:
                self._report_progress("正在拉取仓库最新内容")
                self._checked_git(VaultGit(vault, proxy_url=self.settings.proxy_url).pull())
            self._report_progress(f"正在分析来源设备 {source_label} 的会话")
            plan = plan_import(self.settings.codex_path, vault, source)
            CodexSyncApp._apply_preview_title_overrides(self, plan)
            transaction = create_import_transaction(self.settings.codex_path, plan)
            try:
                self._report_progress("正在合并会话内容")
                result = apply_import(plan)
                self._report_progress("正在修复标题和侧栏索引")
                repair = repair_indexes(self.settings.codex_path, {}, create_backup=False, preferred_titles=plan.title_updates)
                finish_import_transaction(transaction, result["counts"])
                prune_backup_history(self.settings.codex_path, keep=1)
            except Exception:
                finish_import_transaction(transaction, plan.counts, status="failed")
                raise
            self.active_plan = plan
            return (
                "结果：成功\n"
                f"新增：{len(result['copied'])}\n"
                f"自动合并：{len(result['merged'])}\n"
                f"相同：{plan.counts.get('identical', 0)}\n"
                f"标题更新：{len(plan.title_updates)}\n"
                f"侧栏新增：{max(repair.inserted, repair.catalog_inserted)}\n"
                "失败：0"
            )
        self._run_task("导入并修复", work, self.refresh_all)

    def undo_latest_import(self) -> None:
        processes = running_codex_processes(os.getpid())
        if processes:
            messagebox.showerror("需要退出相关程序", "撤销前请退出 Codex、ChatGPT 和 Codex++。")
            return
        transaction = latest_reversible_transaction(self.settings.codex_path)
        if not transaction:
            messagebox.showinfo("没有可撤销记录", "当前没有可撤销的导入。")
            return
        if not messagebox.askyesno("确认撤销", "将删除该次新增的会话，并恢复被合并的会话、数据库和侧栏索引。若导入后会话已变化，程序会拒绝撤销。是否继续？"):
            return
        def work() -> str:
            self._report_progress("正在校验并撤销最近一次导入")
            result = rollback_import_transaction(self.settings.codex_path, transaction)
            return (
                "结果：成功\n"
                f"删除新增：{result['removed']}\n"
                f"恢复合并：{result['restored_sessions']}\n"
                f"恢复状态文件：{result['restored_state']}\n"
                "失败：0"
            )
        self._run_task("撤销最近一次导入", work, self.refresh_all)

    def clear_backups(self) -> None:
        if not messagebox.askyesno("确认清理", "将永久删除同步备份、旧导入备份和旧差异副本；删除后不能撤销历史导入。是否继续？"):
            return
        def work() -> str:
            self._report_progress("正在清理历史备份")
            result = clear_backup_storage(self.settings.codex_path)
            return f"结果：成功\n删除文件：{result['files']}\n释放空间：{self._format_bytes(result['bytes'])}\n失败：0"
        self._run_task("清理备份", work, self.refresh_backups)

    def _show_import_plan(self, plan: Any) -> None:
        self.active_plan = plan
        self.import_tree.delete(*self.import_tree.get_children())
        rows = (
            ("copy", "新增", len(items_for_category(plan, "copy")), "本机不存在，将追加；点击查看"),
            ("identical", "相同", len(items_for_category(plan, "identical")), "内容相同，无需处理；点击查看"),
            ("conflict", "自动合并", len(items_for_category(plan, "conflict")), "内容不同，将后台合并；点击查看三个版本"),
            ("failure", "失败", len(items_for_category(plan, "failure")), "缺少文件或校验失败；点击查看原因"),
            ("title-update", "标题更新", len(items_for_category(plan, "title-update")), "采用最终标题；点击查看或修改"),
        )
        for key, name, count, meaning in rows:
            self.import_tree.insert("", "end", iid=key, values=(name, count, meaning))

    def _apply_preview_title_overrides(self, plan: Any) -> int:
        overrides = getattr(self, "title_overrides", {}).get(plan.source_device, {})
        return apply_title_overrides(plan, overrides)

    def _remember_title_override(self, task_id: str, title: str) -> None:
        if self.active_plan is None:
            return
        source = self.active_plan.source_device
        self.title_overrides.setdefault(source, {})[task_id] = title
        apply_title_overrides(self.active_plan, {task_id: title})
        if self.import_tree.exists("title-update"):
            self.import_tree.set(
                "title-update",
                "count",
                len(items_for_category(self.active_plan, "title-update")),
            )

    def _open_import_action_from_event(self, event: tk.Event) -> None:
        row = self.import_tree.identify_row(event.y)
        if not row:
            return
        self.import_tree.selection_set(row)
        self.import_tree.focus(row)
        self._open_import_action(row)

    def _open_selected_import_action(self) -> None:
        selection = self.import_tree.selection()
        if selection:
            self._open_import_action(selection[0])

    def _open_import_action(self, category: str) -> None:
        plan = self.active_plan
        if plan is None:
            messagebox.showinfo("尚未生成预览", "请先点击“预览导入”。")
            return
        items = items_for_category(plan, category)
        if not items:
            messagebox.showinfo("没有对应内容", "该动作当前没有可预览的会话。")
            return
        ImportPreviewDialog(
            self,
            plan,
            category,
            self.title_overrides.get(plan.source_device, {}),
            self._remember_title_override,
        )

    def _require_vault(self) -> Path | None:
        vault = self.settings.vault
        if not vault:
            messagebox.showwarning("未配置仓库", "请先在设置中选择本地同步仓库。")
            self.show_page("maintenance")
            return None
        if not (vault / ".git").exists():
            messagebox.showwarning("仓库尚未连接", "请运行首次配置向导，连接或创建私有同步仓库。")
            return None
        return vault

    def _checked_git(self, result: Any) -> str:
        if not result.ok:
            if result.output:
                self.logger.error("Git 命令完整错误输出：\n%s", result.output)
            reason = compact_failure_reason(result.output)
            raise RuntimeError(f"结果：失败\n原因：{reason}")
        return result.output

    def _run_task(
        self,
        label: str,
        function: Callable[[], Any],
        callback: Callable[..., None] | None = None,
        callback_with_result: bool = False,
        error_callback: Callable[[Exception], None] | None = None,
    ) -> None:
        if self._busy:
            return
        self._busy = True
        for button in self.task_buttons:
            button.configure(state="disabled")
        self._set_task_state(label, active=True)
        self.logger.info("开始：%s", label)
        def worker() -> None:
            try:
                result = function()
                self.messages.put(("success", label, result, callback, callback_with_result))
            except Exception as exc:
                self.messages.put(("error", label, exc, traceback.format_exc(), error_callback))
        threading.Thread(target=worker, daemon=True).start()

    def _report_progress(self, text: str) -> None:
        self.messages.put(("progress", text))

    def _set_task_state(self, text: str, *, active: bool, failed: bool = False) -> None:
        if active:
            self.task_progress.start(12)
        else:
            self.task_progress.stop()
            self.task_progress.configure(value=0)
        self._set_status_text(text, failed=failed)
        for window in self.winfo_children():
            if isinstance(window, OnboardingWizard):
                window.set_task_state(text, active=active, failed=failed)

    def _set_status_text(self, text: str, *, failed: bool = False) -> None:
        self.busy_text.set(text)
        self.busy_label.configure(style="Error.Status.TEntry" if failed else "Status.TEntry")
        self.after_idle(self._reset_status_scroll)

    def _reset_status_scroll(self) -> None:
        self.busy_label.xview_moveto(0.0)

    def _poll_messages(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                if message[0] == "log":
                    self.log_text.insert("end", message[1] + "\n")
                    self.log_text.see("end")
                elif message[0] == "progress":
                    self._set_task_state(str(message[1]), active=True)
                elif message[0] == "success":
                    _, label, result, callback, callback_with_result = message
                    self._busy = False
                    for button in self.task_buttons:
                        button.configure(state="normal")
                    self._set_task_state("就绪", active=False)
                    self.logger.info("完成：%s", label)
                    if callback:
                        callback(result) if callback_with_result else callback()
                    if isinstance(result, str) and result:
                        messagebox.showinfo(label, result)
                    elif isinstance(result, Path):
                        messagebox.showinfo(label, str(result))
                elif message[0] == "error":
                    _, label, exc, error_trace, error_callback = message
                    self._busy = False
                    for button in self.task_buttons:
                        button.configure(state="normal")
                    self._set_task_state("失败", active=False, failed=True)
                    self.logger.error("%s 失败：%s\n%s", label, exc, error_trace)
                    if label == "刷新检查":
                        self.overview_tree.delete(*self.overview_tree.get_children())
                        self.overview_tree.insert("", "end", values=("环境检查", "失败", str(exc)))
                    if error_callback:
                        error_callback(exc)
                    messagebox.showerror(label + "失败", str(exc))
        except queue.Empty:
            pass
        self.after(120, self._poll_messages)

    def clear_logs(self) -> None:
        if not messagebox.askyesno("确认清理", "将清空当前运行日志和轮转日志。此操作不影响会话或同步仓库。是否继续？"):
            return
        handler = self.log_file_handler
        handler.acquire()
        try:
            handler.flush()
            handler.stream.seek(0)
            handler.stream.truncate(0)
            rotated = Path(str(handler.baseFilename) + ".1")
            if rotated.is_file():
                rotated.unlink()
        finally:
            handler.release()
        self.log_text.delete("1.0", "end")
        self._set_status_text("日志已清理")

    def maybe_show_onboarding(self) -> None:
        if not self.settings.onboarding_complete:
            self.open_onboarding()

    def open_onboarding(self, initial_step: int = 0) -> None:
        existing = next((window for window in self.winfo_children() if isinstance(window, OnboardingWizard)), None)
        if existing:
            existing.lift(self)
            existing.focus_force()
            return
        OnboardingWizard(self, initial_step=initial_step)

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(value)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if size < 1024 or unit == "GiB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GiB"

    @staticmethod
    def _open_path(path: Path) -> None:
        if not path.exists():
            messagebox.showwarning("路径不存在", str(path))
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex conversation synchronization desktop tool")
    parser.add_argument("--diagnose", action="store_true", help="print environment diagnostics and exit")
    parser.add_argument("--codex-home", type=Path, help="override Codex data directory for diagnostics")
    parser.add_argument("--vault", type=Path, help="override sync vault for diagnostics")
    parser.add_argument("--smoke-ui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-onboarding", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-import-preview", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-taskbar", action="store_true", help=argparse.SUPPRESS)
    return parser


def configure_cli_output_encoding() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass


def main() -> None:
    args = build_parser().parse_args()
    store = SettingsStore()
    settings = store.load()
    if args.diagnose:
        configure_cli_output_encoding()
        print(diagnostics_json(args.codex_home or settings.codex_path, args.vault or settings.vault, settings.proxy_url))
        return
    if sys.platform == "darwin" and not getattr(sys, "frozen", False) and tk.TkVersion < 8.6:
        if args.smoke_ui or args.smoke_onboarding or args.smoke_import_preview:
            interpreter = tk.Tcl()
            print(f"ui-import-smoke-ok (Tk {interpreter.eval('info patchlevel')}; window skipped because Tk 8.6+ is required)")
            return
        raise SystemExit(
            "The macOS system Python uses Tk 8.5, which cannot open this UI on the current macOS release. "
            "Use the packaged macOS app, or run the source with Python 3.11+ and Tk 8.6+."
        )
    configure_windows_app_identity()
    app = CodexSyncApp(store)
    if args.smoke_taskbar:
        if os.name != "nt":
            print("taskbar-smoke-skipped (non-Windows)")
            app.destroy()
            return
        app.after(220, app.quit)
        app.mainloop()
        if not app.chrome.is_taskbar_registered():
            app.destroy()
            raise RuntimeError("Packaged Windows app was not registered as a taskbar window")
        print("taskbar-smoke-ok")
        app.destroy()
        return
    if args.smoke_onboarding:
        app.withdraw()
        wizard = OnboardingWizard(app)
        wizard.repository_mode.set("create")
        wizard.repositories_loaded = True
        wizard.step = 3
        wizard._show_step()
        wizard.update()
        if not wizard.next_button.winfo_ismapped() or wizard.page_canvas.winfo_height() <= 1:
            wizard.destroy()
            app.destroy()
            raise RuntimeError("Onboarding layout did not expose its fixed action bar and scrollable content")
        app.after(120, app.quit)
        app.mainloop()
        if wizard.winfo_exists():
            wizard.destroy()
        app.destroy()
        return
    if args.smoke_import_preview:
        from .core.models import ImportItem, ImportPlan

        app.withdraw()
        item = ImportItem(
            "conflict",
            "sessions/smoke.jsonl",
            Path("missing-source.jsonl"),
            Path("missing-local.jsonl"),
            merged_content=(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "preview smoke"},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8"),
            task_id="preview-smoke-task",
            source_title="Preview smoke",
        )
        plan = ImportPlan(
            source_device="preview-smoke-device",
            items=[item],
            title_updates={item.task_id: item.source_title},
        )
        dialog = ImportPreviewDialog(app, plan, "conflict", {}, lambda _task_id, _title: None)
        dialog.update_idletasks()
        if dialog.current_item is None or dialog.current_item.task_id != item.task_id:
            raise RuntimeError("Import preview did not select the smoke-test session")
        if "preview smoke" not in dialog.preview_text.get("1.0", "end"):
            raise RuntimeError("Import preview did not render merged conversation text")
        dialog.destroy()
        app.destroy()
        return
    if args.smoke_ui:
        app.withdraw()
        app.update_idletasks()
        app.destroy()
        return
    app.mainloop()


if __name__ == "__main__":
    main()
