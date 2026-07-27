from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from . import __version__
from .core.backups import create_consistent_backup, restore_backup
from .core.config import Settings, SettingsStore, default_app_home, device_slug
from .core.diagnostics import collect_diagnostics, diagnostics_json
from .core.git_client import VaultGit
from .core.index_repair import repair_indexes
from .core.processes import running_codex_processes
from .core.sessions import apply_import, export_sanitized_sessions, list_source_devices, plan_import


class QueueLogHandler(logging.Handler):
    def __init__(self, messages: queue.Queue):
        super().__init__()
        self.messages = messages

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.put(("log", self.format(record)))


class CodexSyncApp(tk.Tk):
    def __init__(self, store: SettingsStore | None = None):
        super().__init__()
        self.store = store or SettingsStore()
        self.settings = self.store.load()
        self.messages: queue.Queue = queue.Queue()
        self.active_plan = None
        self._busy = False
        self.title(f"Codex Sync Desktop {__version__}")
        self.geometry("1040x720")
        self.minsize(860, 600)
        self.configure(background="#f3f5f7")
        self._configure_logging()
        self._configure_styles()
        self._build_ui()
        self.after(120, self._poll_messages)
        self.after(250, self.refresh_all)

    def report_callback_exception(self, exc_type: type[BaseException], exc: BaseException, trace: Any) -> None:
        self.logger.error("界面操作失败：%s", exc, exc_info=(exc_type, exc, trace))
        self.busy_label.configure(text="失败")
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
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(queue_handler)
        logger.addHandler(file_handler)
        self.logger = logger

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f7")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f3f5f7", foreground="#18212b")
        style.configure("Panel.TLabel", background="#ffffff", foreground="#18212b")
        style.configure("Title.TLabel", font=("TkDefaultFont", 18, "bold"), background="#f3f5f7")
        style.configure("Muted.TLabel", foreground="#66717d", background="#f3f5f7")
        style.configure("Status.TLabel", foreground="#344454", background="#e8edf2", padding=(10, 6))
        style.configure("Accent.TButton", foreground="#ffffff", background="#176b55", padding=(12, 7))
        style.map("Accent.TButton", background=[("active", "#125442"), ("disabled", "#93aaa3")])
        style.configure("TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=28, background="#ffffff", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("TkDefaultFont", 10, "bold"))
        style.configure("TNotebook", background="#f3f5f7", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8))

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.pack(fill="x")
        ttk.Label(header, text="Codex Sync Desktop", style="Title.TLabel").pack(side="left")
        self.busy_label = ttk.Label(header, text="就绪", style="Status.TLabel")
        self.busy_label.pack(side="right")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(4, 16))
        self.overview_tab = ttk.Frame(self.notebook, padding=14)
        self.sync_tab = ttk.Frame(self.notebook, padding=14)
        self.devices_tab = ttk.Frame(self.notebook, padding=14)
        self.conflicts_tab = ttk.Frame(self.notebook, padding=14)
        self.backups_tab = ttk.Frame(self.notebook, padding=14)
        self.paths_tab = ttk.Frame(self.notebook, padding=14)
        self.logs_tab = ttk.Frame(self.notebook, padding=14)
        self.settings_tab = ttk.Frame(self.notebook, padding=14)
        for frame, title in (
            (self.overview_tab, "概览"), (self.sync_tab, "同步与导入"), (self.devices_tab, "设备"),
            (self.conflicts_tab, "冲突"), (self.backups_tab, "备份与回滚"), (self.paths_tab, "路径映射"),
            (self.logs_tab, "日志"), (self.settings_tab, "设置"),
        ):
            self.notebook.add(frame, text=title)
        self._build_overview()
        self._build_sync()
        self._build_devices()
        self._build_conflicts()
        self._build_backups()
        self._build_paths()
        self._build_logs()
        self._build_settings()

    def _build_overview(self) -> None:
        toolbar = ttk.Frame(self.overview_tab)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="刷新检查", command=self.refresh_all).pack(side="left")
        ttk.Button(toolbar, text="打开 Codex 目录", command=lambda: self._open_path(self.settings.codex_path)).pack(side="left", padx=6)
        self.overview_tree = self._tree(self.overview_tab, ("item", "status", "detail"), (180, 120, 590))

    def _build_sync(self) -> None:
        actions = ttk.Frame(self.sync_tab)
        actions.pack(fill="x", pady=(0, 10))
        ttk.Button(actions, text="拉取仓库", command=self.pull_vault).pack(side="left")
        ttk.Button(actions, text="导出并推送", style="Accent.TButton", command=self.export_and_push).pack(side="left", padx=6)
        ttk.Label(actions, text="来源设备:").pack(side="left", padx=(18, 5))
        self.source_device = tk.StringVar()
        self.device_combo = ttk.Combobox(actions, textvariable=self.source_device, state="readonly", width=24)
        self.device_combo.pack(side="left")
        ttk.Button(actions, text="预览导入", command=self.preview_import).pack(side="left", padx=6)
        ttk.Button(actions, text="导入并修复侧栏", command=self.import_and_repair).pack(side="left")
        self.import_tree = self._tree(self.sync_tab, ("action", "count", "meaning"), (180, 100, 610))

    def _build_devices(self) -> None:
        toolbar = ttk.Frame(self.devices_tab)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="刷新设备", command=self.refresh_devices).pack(side="left")
        self.devices_tree = self._tree(self.devices_tab, ("device", "sessions", "exported", "manifest"), (220, 100, 190, 360))

    def _build_conflicts(self) -> None:
        toolbar = ttk.Frame(self.conflicts_tab)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="刷新冲突", command=self.refresh_conflicts).pack(side="left")
        ttk.Button(toolbar, text="打开冲突目录", command=lambda: self._open_path(self.settings.codex_path / "import-conflicts")).pack(side="left", padx=6)
        self.conflict_tree = self._tree(self.conflicts_tab, ("date", "device", "file", "path"), (160, 180, 260, 300))

    def _build_backups(self) -> None:
        toolbar = ttk.Frame(self.backups_tab)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="立即备份", command=self.create_backup).pack(side="left")
        ttk.Button(toolbar, text="恢复所选备份", command=self.restore_selected_backup).pack(side="left", padx=6)
        ttk.Button(toolbar, text="刷新", command=self.refresh_backups).pack(side="left")
        self.backup_tree = self._tree(self.backups_tab, ("created", "files", "path"), (180, 100, 570))

    def _build_paths(self) -> None:
        toolbar = ttk.Frame(self.paths_tab)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="添加映射", command=self.add_mapping).pack(side="left")
        ttk.Button(toolbar, text="删除所选", command=self.remove_mapping).pack(side="left", padx=6)
        self.paths_tree = self._tree(self.paths_tab, ("source", "target"), (430, 430))

    def _build_logs(self) -> None:
        toolbar = ttk.Frame(self.logs_tab)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="清空显示", command=lambda: self.log_text.delete("1.0", "end")).pack(side="left")
        ttk.Button(toolbar, text="打开日志文件", command=lambda: self._open_path(self.store.app_home / "codex-sync.log")).pack(side="left", padx=6)
        self.log_text = tk.Text(self.logs_tab, wrap="word", borderwidth=1, relief="solid", font=("TkFixedFont", 10), background="#101820", foreground="#d7e2ea")
        self.log_text.pack(fill="both", expand=True)

    def _build_settings(self) -> None:
        panel = ttk.Frame(self.settings_tab, style="Panel.TFrame", padding=18)
        panel.pack(fill="x")
        self.setting_vars = {
            "codex_home": tk.StringVar(value=self.settings.codex_home),
            "vault_path": tk.StringVar(value=self.settings.vault_path),
            "vault_remote": tk.StringVar(value=self.settings.vault_remote),
            "device_name": tk.StringVar(value=self.settings.device_name),
        }
        labels = (("codex_home", "Codex 数据目录"), ("vault_path", "本地同步仓库"), ("vault_remote", "GitHub 仓库地址"), ("device_name", "设备名称"))
        for row, (key, label) in enumerate(labels):
            ttk.Label(panel, text=label, style="Panel.TLabel", width=18).grid(row=row, column=0, sticky="w", pady=7)
            ttk.Entry(panel, textvariable=self.setting_vars[key]).grid(row=row, column=1, sticky="ew", pady=7)
            if key in ("codex_home", "vault_path"):
                ttk.Button(panel, text="选择", command=lambda k=key: self.choose_directory(k)).grid(row=row, column=2, padx=(8, 0))
        panel.columnconfigure(1, weight=1)
        buttons = ttk.Frame(self.settings_tab)
        buttons.pack(fill="x", pady=12)
        ttk.Button(buttons, text="保存设置", style="Accent.TButton", command=self.save_settings).pack(side="left")
        ttk.Button(buttons, text="初始化/克隆仓库", command=self.prepare_vault).pack(side="left", padx=6)

    def _tree(self, parent: ttk.Frame, columns: tuple[str, ...], widths: tuple[int, ...]) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        titles = {"item": "检查项", "status": "状态", "detail": "详情", "action": "动作", "count": "数量", "meaning": "说明", "device": "设备", "sessions": "会话数", "exported": "导出时间", "manifest": "清单", "date": "批次", "file": "文件", "path": "路径", "created": "创建时间", "files": "文件数", "source": "源路径", "target": "目标路径"}
        for column, width in zip(columns, widths):
            tree.heading(column, text=titles.get(column, column))
            tree.column(column, width=width, minwidth=70, stretch=True)
        return tree

    def refresh_all(self) -> None:
        self.overview_tree.delete(*self.overview_tree.get_children())
        self.overview_tree.insert("", "end", values=("环境检查", "检查中", "正在读取 Codex 和 Git 环境"))
        self._run_task(
            "刷新检查",
            lambda: collect_diagnostics(self.settings.codex_path, self.settings.vault),
            self._show_overview,
            callback_with_result=True,
        )

    def _show_overview(self, diagnostics: dict[str, Any]) -> None:
        self.overview_tree.delete(*self.overview_tree.get_children())
        rows = [
            ("Codex 数据目录", "正常" if diagnostics["codex_home_exists"] else "未找到", diagnostics["codex_home"]),
            ("本机会话", str(diagnostics["sessions"]), "JSONL 会话文件"),
            ("状态数据库", str(len(diagnostics["databases"])), ", ".join(Path(item).name for item in diagnostics["databases"]) or "未找到"),
            ("侧栏索引", "正常" if diagnostics["session_index"] else "缺失", "session_index.jsonl"),
            ("Git", "正常" if diagnostics["git"] else "缺失", "GitHub 仓库同步"),
            ("Git LFS", "正常" if diagnostics["git_lfs"] else "缺失", "用于包含 Git LFS 钩子的同步仓库"),
            ("GitHub CLI", "已登录" if diagnostics["gh_authenticated"] else "未登录", "gh auth login" if not diagnostics["gh_authenticated"] else "认证可用"),
            ("相关进程", str(len(diagnostics["running_processes"])), ", ".join(item["name"] for item in diagnostics["running_processes"]) or "未检测到"),
            ("同步仓库", "正常" if diagnostics.get("vault_exists") else "未配置", str(self.settings.vault or "")),
        ]
        for row in rows:
            self.overview_tree.insert("", "end", values=row)
        for label, refresh in (
            ("设备", self.refresh_devices),
            ("冲突", self.refresh_conflicts),
            ("备份", self.refresh_backups),
            ("路径映射", self.refresh_paths),
        ):
            try:
                refresh()
            except Exception:
                self.logger.exception("刷新%s失败", label)

    def refresh_devices(self) -> None:
        self.devices_tree.delete(*self.devices_tree.get_children())
        vault = self.settings.vault
        devices = list_source_devices(vault) if vault else []
        for device in devices:
            manifest_path = vault / "sessions-text" / "devices" / device / "manifest.json"
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                row = (device, len(data.get("sessions", [])), data.get("exported_at", "旧格式"), str(manifest_path))
            except (OSError, ValueError):
                row = (device, "错误", "", str(manifest_path))
            self.devices_tree.insert("", "end", values=row)
        self.device_combo["values"] = devices
        if devices and self.source_device.get() not in devices:
            others = [item for item in devices if item != device_slug(self.settings.device_name)]
            self.source_device.set((others or devices)[0])

    def refresh_conflicts(self) -> None:
        self.conflict_tree.delete(*self.conflict_tree.get_children())
        root = self.settings.codex_path / "import-conflicts"
        if not root.exists():
            return
        for path in sorted(root.rglob("*.jsonl"), reverse=True):
            relative = path.relative_to(root)
            parts = relative.parts
            self.conflict_tree.insert("", "end", values=(parts[0] if parts else "", parts[1] if len(parts) > 1 else "", path.name, str(path)))

    def refresh_backups(self) -> None:
        self.backup_tree.delete(*self.backup_tree.get_children())
        root = self.settings.codex_path / "sync-backups"
        if not root.exists():
            return
        for path in sorted((item for item in root.iterdir() if item.is_dir()), reverse=True):
            files = len([item for item in path.rglob("*") if item.is_file() and item.name != "backup.json"])
            self.backup_tree.insert("", "end", iid=str(path), values=(path.name, files, str(path)))

    def refresh_paths(self) -> None:
        self.paths_tree.delete(*self.paths_tree.get_children())
        for source, target in self.settings.path_mappings.items():
            self.paths_tree.insert("", "end", iid=source, values=(source, target))

    def save_settings(self) -> None:
        for key, variable in self.setting_vars.items():
            setattr(self.settings, key, variable.get().strip())
        self.store.save(self.settings)
        self.logger.info("设置已保存")
        self.refresh_all()

    def choose_directory(self, key: str) -> None:
        selected = filedialog.askdirectory(initialdir=self.setting_vars[key].get() or str(Path.home()))
        if selected:
            self.setting_vars[key].set(selected)

    def add_mapping(self) -> None:
        source = simpledialog.askstring("添加路径映射", "源设备路径前缀：", parent=self)
        if not source:
            return
        target = simpledialog.askstring("添加路径映射", "本机路径前缀：", parent=self)
        if not target:
            return
        self.settings.path_mappings[source] = target
        self.store.save(self.settings)
        self.refresh_paths()

    def remove_mapping(self) -> None:
        selected = self.paths_tree.selection()
        if selected:
            self.settings.path_mappings.pop(selected[0], None)
            self.store.save(self.settings)
            self.refresh_paths()

    def prepare_vault(self) -> None:
        self.save_settings()
        vault = self._require_vault()
        if vault:
            self._run_task("初始化仓库", lambda: VaultGit(vault, self.settings.vault_remote).prepare(), self.refresh_all)

    def pull_vault(self) -> None:
        vault = self._require_vault()
        if vault:
            self._run_task("拉取仓库", lambda: self._checked_git(VaultGit(vault).pull()), self.refresh_devices)

    def export_and_push(self) -> None:
        vault = self._require_vault()
        if not vault:
            return
        def work() -> str:
            report = export_sanitized_sessions(self.settings.codex_path, vault, self.settings.device_name)
            self.logger.info("已导出 %s 个完整文字会话，保留敏感字段，移除 %s 个媒体或二进制块", report.sessions, report.media_removed)
            if self.settings.auto_push_after_export:
                result = VaultGit(vault).commit_and_push(f"sync: update {device_slug(self.settings.device_name)}")
                self._checked_git(result)
            return f"导出完成：{report.sessions} 个会话，{report.output_bytes / 1024 / 1024:.1f} MiB"
        self._run_task("导出并推送", work, self.refresh_devices)

    def preview_import(self) -> None:
        vault = self._require_vault()
        source = self.source_device.get()
        if not vault or not source:
            messagebox.showwarning("缺少来源", "请选择来源设备。")
            return
        def work() -> Any:
            if self.settings.auto_pull_before_import:
                self._checked_git(VaultGit(vault).pull())
            return plan_import(self.settings.codex_path, vault, source)
        self._run_task("预览导入", work, self._show_import_plan, callback_with_result=True)

    def import_and_repair(self) -> None:
        vault = self._require_vault()
        source = self.source_device.get()
        if not vault or not source:
            messagebox.showwarning("缺少来源", "请选择来源设备。")
            return
        processes = running_codex_processes(os.getpid())
        if processes:
            names = ", ".join(f"{item.name} (PID {item.pid})" for item in processes)
            messagebox.showerror("需要退出相关程序", f"修复数据库前请退出 Codex、ChatGPT 和 Codex++。\n\n检测到：{names}")
            return
        if not messagebox.askyesno("确认导入", "将创建一致性备份、追加新会话，并按内容和时间合并冲突后重建侧栏索引。双方原文件都会保留备份。是否继续？"):
            return
        def work() -> str:
            if self.settings.auto_pull_before_import:
                self._checked_git(VaultGit(vault).pull())
            plan = plan_import(self.settings.codex_path, vault, source)
            result = apply_import(plan)
            repair = repair_indexes(self.settings.codex_path, self.settings.path_mappings, create_backup=True)
            self.active_plan = plan
            return f"导入 {len(result['copied'])} 个会话，合并 {len(result['merged'])} 个冲突；侧栏新增 {repair.inserted} 项。备份：{repair.backup_dir}"
        self._run_task("导入并修复", work, self.refresh_all)

    def create_backup(self) -> None:
        self._run_task("创建备份", lambda: create_consistent_backup(self.settings.codex_path), self.refresh_backups)

    def restore_selected_backup(self) -> None:
        selected = self.backup_tree.selection()
        if not selected:
            messagebox.showwarning("未选择备份", "请先选择一个备份。")
            return
        processes = running_codex_processes(os.getpid())
        if processes:
            messagebox.showerror("需要退出相关程序", "恢复前请退出 Codex、ChatGPT 和 Codex++。")
            return
        backup = Path(selected[0])
        if not messagebox.askyesno("确认回滚", f"恢复备份 {backup.name}？当前索引数据库将先保留一份新备份。"):
            return
        def work() -> str:
            current = create_consistent_backup(self.settings.codex_path)
            restored = restore_backup(self.settings.codex_path, backup)
            return f"已恢复 {len(restored)} 个文件；恢复前状态保存在 {current}"
        self._run_task("恢复备份", work, self.refresh_all)

    def _show_import_plan(self, plan: Any) -> None:
        self.active_plan = plan
        self.import_tree.delete(*self.import_tree.get_children())
        meanings = {"copy": "本机不存在，将追加", "identical": "内容相同，无需处理", "conflict": "同名内容不同，将按内容和时间合并", "missing-source": "仓库缺少源文件", "invalid-source-hash": "文件未通过清单校验"}
        for action in ("copy", "identical", "conflict", "missing-source", "invalid-source-hash"):
            count = plan.counts.get(action, 0)
            self.import_tree.insert("", "end", values=(action, count, meanings[action]))

    def _require_vault(self) -> Path | None:
        vault = self.settings.vault
        if not vault:
            messagebox.showwarning("未配置仓库", "请先在设置中选择本地同步仓库。")
            self.notebook.select(self.settings_tab)
            return None
        if not (vault / ".git").exists():
            messagebox.showwarning("仓库未初始化", "请先在设置中初始化或克隆仓库。")
            return None
        return vault

    def _checked_git(self, result: Any) -> str:
        if not result.ok:
            raise RuntimeError(result.output or "Git command failed")
        return result.output

    def _run_task(
        self,
        label: str,
        function: Callable[[], Any],
        callback: Callable[..., None] | None = None,
        callback_with_result: bool = False,
    ) -> None:
        if self._busy:
            return
        self._busy = True
        self.busy_label.configure(text=label + "...")
        self.logger.info("开始：%s", label)
        def worker() -> None:
            try:
                result = function()
                self.messages.put(("success", label, result, callback, callback_with_result))
            except Exception as exc:
                self.messages.put(("error", label, exc))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_messages(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                if message[0] == "log":
                    self.log_text.insert("end", message[1] + "\n")
                    self.log_text.see("end")
                elif message[0] == "success":
                    _, label, result, callback, callback_with_result = message
                    self._busy = False
                    self.busy_label.configure(text="就绪")
                    self.logger.info("完成：%s", label)
                    if callback:
                        callback(result) if callback_with_result else callback()
                    if isinstance(result, str) and result:
                        messagebox.showinfo(label, result)
                    elif isinstance(result, Path):
                        messagebox.showinfo(label, str(result))
                elif message[0] == "error":
                    _, label, exc = message
                    self._busy = False
                    self.busy_label.configure(text="失败")
                    self.logger.exception("%s 失败：%s", label, exc)
                    if label == "刷新检查":
                        self.overview_tree.delete(*self.overview_tree.get_children())
                        self.overview_tree.insert("", "end", values=("环境检查", "失败", str(exc)))
                    messagebox.showerror(label + "失败", str(exc))
        except queue.Empty:
            pass
        self.after(120, self._poll_messages)

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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    store = SettingsStore()
    settings = store.load()
    if args.diagnose:
        print(diagnostics_json(args.codex_home or settings.codex_path, args.vault or settings.vault))
        return
    if sys.platform == "darwin" and not getattr(sys, "frozen", False) and tk.TkVersion < 8.6:
        if args.smoke_ui:
            interpreter = tk.Tcl()
            print(f"ui-import-smoke-ok (Tk {interpreter.eval('info patchlevel')}; window skipped because Tk 8.6+ is required)")
            return
        raise SystemExit(
            "The macOS system Python uses Tk 8.5, which cannot open this UI on the current macOS release. "
            "Use the packaged macOS app, or run the source with Python 3.11+ and Tk 8.6+."
        )
    app = CodexSyncApp(store)
    if args.smoke_ui:
        app.withdraw()
        app.update_idletasks()
        app.destroy()
        return
    app.mainloop()


if __name__ == "__main__":
    main()
