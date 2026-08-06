from __future__ import annotations

import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from typing import Any

from .core.onboarding import (
    GH_DOWNLOAD_URL,
    GIT_DOWNLOAD_URL,
    GITHUB_DEVICE_URL,
    GITHUB_SIGNUP_URL,
    ConnectivityResult,
    DependencyInstallResult,
    RepositorySetupResult,
    check_github_connectivity,
    clear_tool_installer_cache,
    connect_private_repository,
    create_private_repository,
    detect_system_proxy,
    github_setup_status,
    launch_dependency_install,
    launch_github_login,
    list_private_repositories,
    open_default_browser,
    validate_proxy_url,
)
from .core.git_client import VaultGit
from .core.git_client import CommandResult
from .core.sessions import NoActiveSessionsError, list_source_device_options
from .ui_theme import COLORS, center_window, vertical_scrollbar_required


def checkmark_text(selected: bool, label: str) -> str:
    return f"{'[✓]' if selected else '[ ]'} {label}"


class OnboardingWizard(tk.Toplevel):
    def __init__(self, app: Any, initial_step: int = 0):
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.title("首次配置向导")
        self.minsize(700, 500)
        self.configure(background=COLORS["background"])
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.step = min(max(int(initial_step), 0), 3)
        self.network_ok = False
        self.account_status: dict[str, object] = {}
        self.dependency_poll_attempts = 0
        self.pages: list[ttk.Frame] = []
        self.confirm_private = tk.BooleanVar(value=False)
        self.china_mode = tk.BooleanVar(value=app.settings.china_network_mode)
        self.proxy_url = tk.StringVar(value=app.settings.proxy_url)
        self.repository_name = tk.StringVar(value="codex-sync-vault")
        existing_remote = str(getattr(app.settings, "vault_remote", "") or "").strip()
        self.repository_mode = tk.StringVar(value="existing" if existing_remote else "create")
        self.repository_reference = tk.StringVar(value=existing_remote)
        self.repositories_loaded = False
        self.repositories_loading = False
        self.setup_in_progress = False
        self._page_scrollbar_visible = False
        self._page_scroll_update_pending = False
        default_vault = app.settings.vault_path or str(Path.home() / "Documents" / "CodexSync" / "codex-sync-vault")
        self.local_path = tk.StringVar(value=default_vault)
        self.codex_home = tk.StringVar(value=app.settings.codex_home)
        self.device_name = tk.StringVar(value=app.settings.device_name)
        self.proxy_url.trace_add("write", lambda *_args: self._invalidate_network())
        for variable in (
            self.confirm_private,
            self.repository_mode,
            self.repository_reference,
            self.repository_name,
            self.local_path,
            self.codex_home,
            self.device_name,
        ):
            variable.trace_add("write", self._update_next_state)
        self._build()
        center_window(self, app, 900, 700)
        self.deiconify()
        self.lift(app)
        self.focus_force()
        self.grab_set()

    def _build(self) -> None:
        shell = ttk.Frame(self, padding=24)
        shell.pack(fill="both", expand=True)
        top = ttk.Frame(shell)
        top.pack(fill="x", pady=(0, 16))
        ttk.Label(top, text="首次配置", style="Title.TLabel").pack(side="left")
        self.progress = ttk.Label(top, text="步骤 1 / 4", style="Status.TLabel")
        self.progress.pack(side="right")
        page_area = ttk.Frame(shell, style="Panel.TFrame")
        page_area.pack(fill="both", expand=True)
        self.page_canvas = tk.Canvas(
            page_area,
            background=COLORS["surface"],
            borderwidth=0,
            highlightthickness=0,
        )
        self.page_scrollbar = ttk.Scrollbar(
            page_area,
            orient="vertical",
            command=self.page_canvas.yview,
            style="Wizard.Vertical.TScrollbar",
        )
        self.page_canvas.configure(yscrollcommand=self.page_scrollbar.set)
        page_area.columnconfigure(0, weight=1)
        page_area.rowconfigure(0, weight=1)
        self.page_canvas.grid(row=0, column=0, sticky="nsew")
        self.page_host = ttk.Frame(self.page_canvas, style="Panel.TFrame", padding=22)
        self.page_window = self.page_canvas.create_window((0, 0), window=self.page_host, anchor="nw")
        self.page_canvas.bind("<Configure>", self._resize_page_host)
        self.page_host.bind("<Configure>", self._schedule_page_scroll_update)
        self.bind("<MouseWheel>", self._scroll_page)
        for builder in (self._welcome_page, self._network_page, self._account_page, self._repository_page):
            page = ttk.Frame(self.page_host, style="Panel.TFrame")
            builder(page)
            self.pages.append(page)
        activity = ttk.Frame(shell)
        activity.pack(fill="x", pady=(14, 0))
        self.activity_progress = ttk.Progressbar(activity, mode="indeterminate", length=180, style="Tech.Horizontal.TProgressbar")
        self.activity_progress.pack(side="left")
        self.activity_label = ttk.Label(activity, text="等待操作", style="Muted.TLabel", anchor="w")
        self.activity_label.pack(side="left", fill="x", expand=True, padx=(12, 0))
        footer = ttk.Frame(shell)
        footer.pack(fill="x", pady=(16, 0))
        self.back_button = ttk.Button(footer, text="上一步", command=self._back)
        self.back_button.pack(side="left")
        ttk.Button(footer, text="稍后配置", command=self.destroy).pack(side="left", padx=8)
        self.next_button = ttk.Button(footer, text="下一步", style="Accent.TButton", command=self._next)
        self.next_button.pack(side="right")
        self._show_step()

    def set_task_state(self, text: str, *, active: bool, failed: bool = False) -> None:
        if not hasattr(self, "activity_progress"):
            return
        if active:
            self.activity_progress.start(12)
            self.activity_label.configure(text=text, style="Activity.TLabel")
        else:
            self.activity_progress.stop()
            self.activity_progress.configure(value=0)
            self.activity_label.configure(text=text, style="ActivityError.TLabel" if failed else "Muted.TLabel")

    def _resize_page_host(self, event: tk.Event[Any]) -> None:
        self.page_canvas.itemconfigure(self.page_window, width=max(int(event.width), 1))
        self._schedule_page_scroll_update()

    def _schedule_page_scroll_update(self, _event: tk.Event[Any] | None = None) -> None:
        if self._page_scroll_update_pending:
            return
        self._page_scroll_update_pending = True
        self.after_idle(self._update_page_scrollregion)

    def _update_page_scrollregion(self) -> None:
        self._page_scroll_update_pending = False
        bounds = self.page_canvas.bbox("all")
        if bounds is None:
            bounds = (0, 0, 0, 0)
        self.page_canvas.configure(scrollregion=bounds)
        content_height = max(int(bounds[3] - bounds[1]), 0)
        viewport_height = max(int(self.page_canvas.winfo_height()), 0)
        required = vertical_scrollbar_required(content_height, viewport_height)
        if required == self._page_scrollbar_visible:
            return
        self._page_scrollbar_visible = required
        if required:
            self.page_scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self.page_scrollbar.grid_remove()
            self.page_canvas.yview_moveto(0.0)
        self.after_idle(self._schedule_page_scroll_update)

    def _reset_page_scroll(self) -> None:
        self.page_canvas.yview_moveto(0.0)
        self._schedule_page_scroll_update()

    def _scroll_page(self, event: tk.Event[Any]) -> None:
        if not self._page_scrollbar_visible or isinstance(event.widget, ttk.Treeview):
            return
        delta = int(getattr(event, "delta", 0))
        if delta:
            self.page_canvas.yview_scroll(-1 if delta > 0 else 1, "units")

    @staticmethod
    def _heading(parent: ttk.Frame, title: str, subtitle: str) -> None:
        ttk.Label(parent, text=title, style="PanelSection.TLabel").pack(anchor="w")
        ttk.Label(parent, text=subtitle, style="PanelMuted.TLabel", wraplength=720, justify="left").pack(anchor="w", pady=(6, 18))

    def _checkmark(self, parent: ttk.Frame, label: str, variable: tk.BooleanVar) -> ttk.Checkbutton:
        display = tk.StringVar(value=checkmark_text(bool(variable.get()), label))

        def refresh(*_args: object) -> None:
            display.set(checkmark_text(bool(variable.get()), label))

        variable.trace_add("write", refresh)
        return ttk.Checkbutton(
            parent,
            textvariable=display,
            variable=variable,
            style="Checkmark.TCheckbutton",
        )

    def _welcome_page(self, page: ttk.Frame) -> None:
        self._heading(page, "准备安全的同步空间", "向导会检查网络和必要工具，登录 GitHub，创建仅你可见的私有仓库，并完成本机配置。")
        items = (
            "同步内容：活动会话的完整文字、任务名称、命令和工具输出。",
            "不会上传：图片、附件二进制、归档或已删除会话。",
            "重要提醒：文字中可能包含 Token、密钥、连接串等敏感信息。",
        )
        for index, item in enumerate(items, 1):
            row = ttk.Frame(page, style="Panel.TFrame")
            row.pack(fill="x", pady=7)
            ttk.Label(row, text=str(index), style="Status.TLabel", width=3, anchor="center").pack(side="left")
            ttk.Label(row, text=item, style="Panel.TLabel", wraplength=650, justify="left").pack(side="left", padx=12)
        self._checkmark(
            page,
            "我确认同步仓库必须保持私有，并理解会话文字可能包含敏感信息。",
            self.confirm_private,
        ).pack(anchor="w", pady=(24, 0))

    def _network_page(self, page: ttk.Frame) -> None:
        self._heading(page, "检查 GitHub 网络连接", "中国大陆网络可能无法直接访问 GitHub。请先启动符合所在地法律和组织规定的代理工具，再填写本机 HTTP 代理地址。")
        self._checkmark(page, "我位于中国大陆或当前网络需要代理", self.china_mode).pack(anchor="w", pady=(0, 14))
        form = ttk.Frame(page, style="Panel.TFrame")
        form.pack(fill="x")
        ttk.Label(form, text="本机代理地址", style="Panel.TLabel", width=16).grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.proxy_url).grid(row=0, column=1, sticky="ew")
        ttk.Button(form, text="读取系统代理", command=self._detect_proxy).grid(row=0, column=2, padx=(8, 0))
        form.columnconfigure(1, weight=1)
        ttk.Label(page, text="示例：http://127.0.0.1:7890。不要填写含账号密码的代理地址。", style="PanelMuted.TLabel").pack(anchor="w", pady=(8, 16))
        ttk.Button(page, text="测试 GitHub 连接", style="Accent.TButton", command=self._test_network).pack(anchor="w")
        self.network_status = ttk.Label(page, text="尚未测试", style="PanelMuted.TLabel")
        self.network_status.pack(anchor="w", pady=(12, 0))

    def _account_page(self, page: ttk.Frame) -> None:
        self._heading(page, "准备 GitHub 账号", "点击登录后，软件会调用系统默认浏览器。账号、密码和二次验证只在 GitHub 官方页面输入，本软件不会读取。")
        actions = ttk.Frame(page, style="Panel.TFrame")
        actions.pack(fill="x", pady=(0, 18))
        ttk.Button(actions, text="没有账号：打开注册", command=lambda: webbrowser.open(GITHUB_SIGNUP_URL)).pack(side="left")
        ttk.Button(actions, text="打开 GitHub 登录", style="Accent.TButton", command=self._launch_login).pack(side="left", padx=8)
        ttk.Button(actions, text="重新打开授权页", command=self._reopen_login_page).pack(side="left")
        ttk.Button(actions, text="重新检测", command=self._refresh_account).pack(side="left")
        self.account_tree = ttk.Treeview(page, columns=("item", "status", "action"), show="headings", height=5)
        for name, title, width in (("item", "检查项", 180), ("status", "状态", 120), ("action", "处理方法", 390)):
            self.account_tree.heading(name, text=title)
            self.account_tree.column(name, width=width, minwidth=90, stretch=True)
        self.account_tree.pack(fill="both", expand=True)
        downloads = ttk.Frame(page, style="Panel.TFrame")
        downloads.pack(fill="x", pady=(12, 0))
        ttk.Button(downloads, text="自动安装/修复必要工具", style="Accent.TButton", command=self._install_dependencies).pack(side="left")
        ttk.Button(downloads, text="下载 Git", command=lambda: webbrowser.open(GIT_DOWNLOAD_URL)).pack(side="left")
        ttk.Button(downloads, text="下载 GitHub CLI", command=lambda: webbrowser.open(GH_DOWNLOAD_URL)).pack(side="left", padx=8)
        self.dependency_status = ttk.Label(page, text="全新设备无需预先配置 GitHub。登录时会自动复制一次性验证码并打开官方授权页。", style="PanelMuted.TLabel", wraplength=700, justify="left")
        self.dependency_status.pack(anchor="w", pady=(10, 0))

    def _repository_page(self, page: ttk.Frame) -> None:
        self._heading(page, "配置私有同步仓库", "可以创建新的私有仓库，也可以连接当前账号已有权限的私有仓库；已有仓库不会被重复创建。")
        mode = ttk.Frame(page, style="Panel.TFrame")
        mode.pack(fill="x", pady=(0, 12))
        ttk.Radiobutton(
            mode,
            text="创建新的私有仓库",
            value="create",
            variable=self.repository_mode,
            command=self._toggle_repository_mode,
        ).pack(side="left")
        ttk.Radiobutton(
            mode,
            text="连接已有私有仓库",
            value="existing",
            variable=self.repository_mode,
            command=self._toggle_repository_mode,
        ).pack(side="left", padx=(18, 0))
        self.repository_choice_host = ttk.Frame(page, style="Panel.TFrame")
        self.repository_choice_host.pack(fill="x", pady=(0, 10))
        self.create_repository_frame = ttk.Frame(self.repository_choice_host, style="Panel.TFrame")
        ttk.Label(self.create_repository_frame, text="新仓库名称", style="Panel.TLabel", width=17).grid(row=0, column=0, sticky="w")
        ttk.Entry(self.create_repository_frame, textvariable=self.repository_name).grid(row=0, column=1, sticky="ew")
        self.create_repository_frame.columnconfigure(1, weight=1)
        self.existing_repository_frame = ttk.Frame(self.repository_choice_host, style="Panel.TFrame")
        ttk.Label(self.existing_repository_frame, text="已有私有仓库", style="Panel.TLabel", width=17).grid(row=0, column=0, sticky="w")
        self.repository_selector = ttk.Combobox(
            self.existing_repository_frame,
            textvariable=self.repository_reference,
            state="normal",
        )
        self.repository_selector.grid(row=0, column=1, sticky="ew")
        ttk.Button(self.existing_repository_frame, text="刷新仓库", command=self._refresh_repositories).grid(row=0, column=2, padx=(8, 0))
        self.existing_repository_frame.columnconfigure(1, weight=1)
        ttk.Label(
            self.existing_repository_frame,
            text="可从列表选择，也可输入 owner/repository 或 GitHub HTTPS 地址。",
            style="PanelMuted.TLabel",
        ).grid(row=1, column=1, sticky="w", pady=(6, 0))
        form = ttk.Frame(page, style="Panel.TFrame")
        form.pack(fill="x")
        fields = (
            ("本地同步目录", self.local_path, True),
            ("Codex 数据目录", self.codex_home, True),
            ("设备名称", self.device_name, False),
        )
        for row, (label, variable, browse) in enumerate(fields):
            ttk.Label(form, text=label, style="Panel.TLabel", width=17).grid(row=row, column=0, sticky="w", pady=7)
            ttk.Entry(form, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=7)
            if browse:
                ttk.Button(form, text="选择", command=lambda value=variable: self._choose_directory(value)).grid(row=row, column=2, padx=(8, 0))
        form.columnconfigure(1, weight=1)
        self.repository_status = ttk.Label(page, text="只有仓库通过私有性和访问权限验证且首次同步成功，向导才会显示全部完成。", style="PanelMuted.TLabel", wraplength=700, justify="left")
        self.repository_status.pack(anchor="w", pady=(18, 0))
        self._toggle_repository_mode()

    def _show_step(self) -> None:
        for page in self.pages:
            page.pack_forget()
        self.pages[self.step].pack(fill="both", expand=True)
        self.progress.configure(text=f"步骤 {self.step + 1} / {len(self.pages)}")
        self.back_button.configure(state="normal" if self.step else "disabled")
        self.next_button.configure(text="创建仓库并首次同步" if self.step == len(self.pages) - 1 else "下一步")
        if self.step == 2:
            self._refresh_account()
        if self.step == 3:
            self._toggle_repository_mode()
        self._update_next_state()
        self.after_idle(self._reset_page_scroll)

    def _step_ready(self) -> bool:
        if self.step == 0:
            return bool(self.confirm_private.get())
        if self.step == 1:
            return bool(self.network_ok)
        account_ready = all(self.account_status.get(key) for key in ("git", "gh", "authenticated"))
        if self.step == 2:
            return account_ready
        if self.step == 3:
            repository_value = (
                self.repository_reference.get().strip()
                if self.repository_mode.get() == "existing"
                else self.repository_name.get().strip()
            )
            return bool(
                self.network_ok
                and account_ready
                and not self.repositories_loading
                and repository_value
                and self.local_path.get().strip()
                and self.codex_home.get().strip()
                and self.device_name.get().strip()
            )
        return False

    def _update_next_state(self, *_args: object) -> None:
        if not hasattr(self, "next_button"):
            return
        state = "disabled" if self.setup_in_progress or not self._step_ready() else "normal"
        self.next_button.configure(state=state)

    def _toggle_repository_mode(self) -> None:
        if not hasattr(self, "repository_choice_host"):
            return
        self.create_repository_frame.pack_forget()
        self.existing_repository_frame.pack_forget()
        existing = self.repository_mode.get() == "existing"
        selected = self.existing_repository_frame if existing else self.create_repository_frame
        selected.pack(fill="x")
        if hasattr(self, "next_button") and self.step == len(self.pages) - 1:
            self.next_button.configure(text="连接并首次同步" if existing else "创建仓库并首次同步")
        if hasattr(self, "repository_status"):
            text = (
                "将验证已有仓库为私有仓库，再安全克隆或连接本地目录。不会重新创建仓库。"
                if existing
                else "仓库不存在时才会创建；同名私有仓库已存在时会安全复用。"
            )
            self.repository_status.configure(text=text)
        self._update_next_state()
        self._schedule_page_scroll_update()
        if existing and self.step == 3 and hasattr(self, "next_button") and not self.repositories_loaded:
            self._refresh_repositories()

    def _refresh_repositories(self) -> None:
        if self.repositories_loading:
            return
        try:
            proxy = validate_proxy_url(self.proxy_url.get())
        except ValueError as exc:
            messagebox.showerror("代理地址错误", str(exc), parent=self)
            return
        self.repositories_loading = True
        self._update_next_state()
        self.repository_status.configure(text="正在读取当前 GitHub 账号可访问的私有仓库...")
        self.app._run_task(
            "读取私有仓库",
            lambda: list_private_repositories(proxy),
            self._show_repositories,
            callback_with_result=True,
            error_callback=self._repository_list_failed,
        )

    def _show_repositories(self, repositories: list[str]) -> None:
        self.repositories_loading = False
        self.repositories_loaded = True
        self.repository_selector.configure(values=repositories)
        current = self.repository_reference.get().strip()
        if not current and repositories:
            self.repository_reference.set(repositories[0])
        if repositories:
            self.repository_status.configure(text=f"已读取 {len(repositories)} 个私有仓库。请选择一个，或手动输入 owner/repository。")
        else:
            self.repository_status.configure(text="当前账号没有返回可访问的私有仓库；可切换为创建新仓库。")
        self._update_next_state()

    def _repository_list_failed(self, exc: Exception) -> None:
        self.repositories_loading = False
        self.repository_status.configure(text=f"读取私有仓库失败：{exc}\n仍可手动输入 owner/repository 后继续验证。")
        self._update_next_state()

    def _back(self) -> None:
        if self.step:
            self.step -= 1
            self._show_step()

    def _next(self) -> None:
        if self.step == 0 and not self.confirm_private.get():
            messagebox.showwarning("尚未就绪", "请先勾选私有仓库和敏感信息确认。", parent=self)
            return
        if self.step == 1 and not self.network_ok:
            messagebox.showwarning("网络尚未通过", "请先测试 GitHub 连接；需要代理时先启动代理并填写地址。", parent=self)
            return
        if self.step == 2:
            if not all(self.account_status.get(key) for key in ("git", "gh", "authenticated")):
                messagebox.showwarning("准备工作未完成", "请安装 Git、GitHub CLI 并完成 GitHub 登录。", parent=self)
                return
        if self.step < len(self.pages) - 1:
            self.step += 1
            self._show_step()
            return
        self._finish_setup()

    def _invalidate_network(self) -> None:
        self.network_ok = False
        if hasattr(self, "network_status"):
            self.network_status.configure(text="代理设置已变化，请重新测试")
        self._update_next_state()

    def _detect_proxy(self) -> None:
        proxy = detect_system_proxy()
        if proxy:
            self.proxy_url.set(proxy)
        else:
            messagebox.showinfo("未检测到代理", "系统没有提供可用的 HTTP/HTTPS 代理。请先启动代理工具，再填写其本机地址。", parent=self)

    def _test_network(self) -> None:
        try:
            proxy = validate_proxy_url(self.proxy_url.get())
        except ValueError as exc:
            messagebox.showerror("代理地址错误", str(exc), parent=self)
            return
        self.network_ok = False
        self._update_next_state()
        self.network_status.configure(text="正在测试 GitHub API...")
        self.app._run_task("测试 GitHub 网络", lambda: check_github_connectivity(proxy), self._show_network_result, callback_with_result=True)

    def _show_network_result(self, result: ConnectivityResult) -> None:
        self.network_ok = result.ok
        if result.ok:
            mode = "通过代理" if result.proxy_used else "直接连接"
            self.app.settings.proxy_url = validate_proxy_url(self.proxy_url.get())
            self.app.settings.china_network_mode = self.china_mode.get()
            self.app.store.save(self.app.settings)
            self.network_status.configure(text=f"连接成功：{mode}，HTTP {result.status}。设置已保存，可继续注册或登录。")
        else:
            hint = "请确认代理已启动、HTTP 端口正确，并允许本软件访问网络。" if self.proxy_url.get().strip() else "请检查网络；中国大陆或受限网络请先启动合规代理并填写 HTTP 地址。"
            self.network_status.configure(text=f"连接失败：{result.reason}\n{hint}")
        self._update_next_state()

    def _launch_login(self) -> None:
        try:
            proxy = validate_proxy_url(self.proxy_url.get())
        except ValueError as exc:
            messagebox.showerror("无法打开登录", str(exc), parent=self)
            return
        if not messagebox.askokcancel(
            "登录 GitHub",
            "软件将使用系统默认浏览器打开 GitHub 官方设备授权页，并自动复制一次性验证码。\n\n"
            "请只在 GitHub 页面输入账号、密码和二次验证码。本软件不会读取或保存这些信息。\n\n"
            "授权完成前请保持此向导打开。",
            parent=self,
        ):
            return
        self.dependency_status.configure(text="正在打开系统默认浏览器并等待授权。验证码会自动复制；如页面未打开，请点击“重新打开授权页”。")

        def work() -> CommandResult:
            result = launch_github_login(self.app.store.app_home, proxy)
            if not result.ok:
                reason = next((line.strip() for line in reversed(result.output.splitlines()) if line.strip()), "GitHub 登录未完成")
                raise RuntimeError(reason)
            return result

        self.app._run_task(
            "GitHub 登录",
            work,
            self._github_login_finished,
            callback_with_result=True,
            error_callback=self._github_login_failed,
        )

    def _github_login_finished(self, _result: CommandResult) -> None:
        self.dependency_status.configure(text="GitHub 登录已完成并通过状态复检。")
        self._refresh_account()
        messagebox.showinfo("GitHub 登录成功", "浏览器授权已完成，登录状态复检通过。", parent=self)

    def _github_login_failed(self, exc: Exception) -> None:
        self.dependency_status.configure(text=f"GitHub 登录失败：{exc}\n请重试登录；浏览器未打开时点击“重新打开授权页”。")

    def _reopen_login_page(self) -> None:
        result = open_default_browser(GITHUB_DEVICE_URL)
        if result.ok:
            self.dependency_status.configure(text=f"{result.output}。请粘贴自动复制的一次性验证码并完成授权。")
            return
        messagebox.showerror("无法打开默认浏览器", result.output, parent=self)

    def _install_dependencies(self) -> None:
        if not messagebox.askyesno(
            "确认安装",
            "软件将自动下载并安装缺少的 Git 和 GitHub CLI。Windows 的 GitHub CLI 会免安装配置到软件目录；只有安装 Git 或 macOS 系统工具时可能请求系统授权。最多占用约 300 MiB 磁盘。是否继续？",
            parent=self,
        ):
            return
        self.dependency_status.configure(text="正在自动准备必要工具，请稍候...")
        self.app._run_task(
            "准备必要工具",
            lambda: {"result": launch_dependency_install(self.app.store.app_home, self.proxy_url.get())},
            self._dependency_installer_opened,
            callback_with_result=True,
            error_callback=self._dependency_install_failed,
        )

    def _dependency_installer_opened(self, payload: dict[str, object]) -> None:
        result = payload.get("result")
        if not isinstance(result, DependencyInstallResult):
            self._dependency_install_failed(RuntimeError("安装结果无效"))
            return
        self.dependency_status.configure(text=result.message)
        if result.completed:
            self._refresh_account()
            return
        messagebox.showinfo("等待系统授权", result.message, parent=self)
        self.dependency_poll_attempts = 0
        self.after(2500, self._poll_dependency_install)

    def _poll_dependency_install(self) -> None:
        try:
            window_exists = bool(self.winfo_exists())
        except tk.TclError:
            return
        if not window_exists or self.dependency_poll_attempts >= 200:
            if window_exists:
                self.dependency_status.configure(text="尚未检测到必要工具。请确认系统安装窗口已经完成，或点击“自动安装/修复必要工具”重试。")
            return
        if self.app._busy:
            self.after(1000, self._poll_dependency_install)
            return
        self.dependency_poll_attempts += 1
        try:
            proxy = validate_proxy_url(self.proxy_url.get())
        except ValueError:
            return
        self.app._run_task(
            "自动检测必要工具",
            lambda: github_setup_status(proxy, self.app.store.app_home),
            self._dependency_poll_result,
            callback_with_result=True,
        )

    def _dependency_poll_result(self, status: dict[str, object]) -> None:
        self._show_account_status(status)
        if status.get("git") and status.get("gh"):
            self.dependency_status.configure(text="必要工具安装完成并已通过启动检测。现在可以点击“打开 GitHub 登录”。")
            messagebox.showinfo("必要工具安装完成", "Git 和 GitHub CLI 已可用，现在可以继续 GitHub 登录。", parent=self)
            return
        self.after(3000, self._poll_dependency_install)

    def _dependency_install_failed(self, exc: Exception) -> None:
        self.dependency_status.configure(text=f"准备失败：{exc}\n可检查网络/代理后重试，或使用旁边的官方下载按钮。")

    def _refresh_account(self) -> None:
        try:
            proxy = validate_proxy_url(self.proxy_url.get())
        except ValueError as exc:
            messagebox.showerror("代理地址错误", str(exc), parent=self)
            return
        self.account_status = {}
        self._update_next_state()
        self.app._run_task(
            "检查 GitHub 登录",
            lambda: github_setup_status(proxy, self.app.store.app_home),
            self._show_account_status,
            callback_with_result=True,
        )

    def _show_account_status(self, status: dict[str, object]) -> None:
        self.account_status = status
        self.account_tree.delete(*self.account_tree.get_children())
        rows = (
            ("Git", status.get("git"), status.get("git_reason") or "点击下方“自动安装/修复必要工具”"),
            ("GitHub CLI", status.get("gh"), status.get("gh_reason") or "点击下方“自动安装/修复必要工具”"),
            ("GitHub 登录", status.get("authenticated"), "未登录时点击“打开 GitHub 登录”"),
        )
        for label, ok, action in rows:
            self.account_tree.insert("", "end", values=(label, "已完成" if ok else "未完成", "无需处理" if ok else action))
        if status.get("git") and status.get("gh"):
            clear_tool_installer_cache(self.app.store.app_home)
            gh_path = str(status.get("gh_path") or "系统 PATH")
            self.dependency_status.configure(text=f"必要工具已安装并通过实际启动检测。GitHub CLI：{gh_path}")
        self._update_next_state()

    def _finish_setup(self) -> None:
        try:
            proxy = validate_proxy_url(self.proxy_url.get())
            codex_home = Path(self.codex_home.get()).expanduser().resolve()
            if not codex_home.is_dir():
                raise FileNotFoundError(f"Codex 数据目录不存在：{codex_home}")
            device_name = self.device_name.get().strip()
            if not device_name:
                raise ValueError("设备名称不能为空")
            local_path = Path(self.local_path.get()).expanduser()
            mode = self.repository_mode.get()
            if mode == "existing":
                repository_value = self.repository_reference.get().strip()
                if not repository_value:
                    raise ValueError("请选择或输入已有 GitHub 私有仓库")
            else:
                repository_value = self.repository_name.get().strip()
                if not repository_value:
                    raise ValueError("新仓库名称不能为空")
        except (OSError, ValueError) as exc:
            messagebox.showerror("配置不完整", str(exc), parent=self)
            return
        existing = mode == "existing"
        self.setup_in_progress = True
        self.repository_status.configure(text="正在验证并连接已有私有仓库..." if existing else "正在创建并验证私有仓库...")
        self.back_button.configure(state="disabled")
        self.next_button.configure(state="disabled", text="正在连接已有仓库..." if existing else "正在创建私有仓库...")
        if existing:
            setup = lambda: connect_private_repository(local_path, repository_value, proxy)
        else:
            setup = lambda: create_private_repository(local_path, repository_value, proxy)
        self.app._run_task(
            "首次自动配置",
            setup,
            lambda result: self._complete(result, proxy, codex_home, device_name),
            callback_with_result=True,
            error_callback=self._setup_failed,
        )

    def _complete(self, result: RepositorySetupResult, proxy: str, codex_home: Path, device_name: str) -> None:
        settings = self.app.settings
        settings.codex_home = str(codex_home)
        settings.vault_path = str(result.local_path)
        settings.vault_remote = result.url.rstrip("/") + ".git"
        settings.device_name = device_name
        settings.proxy_url = proxy
        settings.china_network_mode = self.china_mode.get()
        settings.onboarding_complete = False
        self.app.store.save(settings)
        for key, variable in self.app.setting_vars.items():
            if hasattr(settings, key):
                variable.set(str(getattr(settings, key)))
        action = "已创建" if result.created else "已连接"
        self.repository_status.configure(
            text=f"私有仓库{action}：{result.owner}/{result.name}。本地同步目录：{result.local_path}。正在拉取并完成首次同步..."
        )
        self.next_button.configure(text="正在首次同步...")
        self.app._run_task(
            "首次同步",
            lambda: {"summary": self._initial_sync_work(result, proxy)},
            lambda payload: self._initial_sync_complete(result, str(payload["summary"])),
            callback_with_result=True,
            error_callback=self._initial_sync_failed,
        )

    def _initial_sync_work(self, result: RepositorySetupResult, proxy: str) -> str:
        self.app._report_progress("正在拉取私有仓库最新内容")
        pulled = VaultGit(result.local_path, proxy_url=proxy).pull()
        self.app._checked_git(pulled)
        if not (self.app.settings.codex_path / "sessions").is_dir():
            sources = list_source_device_options(result.local_path)
            if sources:
                names = "、".join(label for label, _key in sources[:5])
                suffix = "等" if len(sources) > 5 else ""
                return (
                    f"已拉取仓库，发现 {len(sources)} 个来源设备：{names}{suffix}。\n"
                    "请退出 ChatGPT/Codex/Codex++，在“同步与导入”中选择来源设备后点击“一键同步”。"
                )
        return self.app._export_and_push_work(result.local_path, force_push=True)

    def _initial_sync_complete(self, result: RepositorySetupResult, summary: str) -> None:
        self.app.settings.onboarding_complete = True
        self.app.store.save(self.app.settings)
        self.destroy()
        self.app.refresh_all()
        self.app.show_page("sync")
        messagebox.showinfo(
            "首次配置全部完成",
            f"私有仓库：{result.owner}/{result.name}\n"
            f"本地同步目录：{result.local_path}\n\n{summary}\n\n"
            "以后换设备时，只需安装软件、登录 GitHub，并在首次配置向导中选择这个已有私有仓库。",
            parent=self.app,
        )

    def _setup_failed(self, exc: Exception) -> None:
        self.setup_in_progress = False
        action = "连接" if self.repository_mode.get() == "existing" else "创建"
        self.repository_status.configure(text=f"{action}失败：{exc}\n请检查上方配置后点击重试。")
        self.back_button.configure(state="normal")
        self.next_button.configure(text=f"重试{action}并首次同步")
        self._update_next_state()

    def _initial_sync_failed(self, exc: Exception) -> None:
        if isinstance(exc, NoActiveSessionsError):
            self.app.settings.onboarding_complete = True
            self.app.store.save(self.app.settings)
            self.destroy()
            self.app.refresh_all()
            self.app.show_page("sync")
            messagebox.showinfo(
                "仓库连接完成，暂无会话",
                "私有同步仓库已经连接成功。\n\n"
                "当前电脑尚未生成 Codex 会话文件。请先打开 ChatGPT/Codex，使用 Codex 完成至少一次对话；"
                f"系统创建 {exc.sessions_path} 后，再点击“一键同步”。",
                parent=self.app,
            )
            return
        self.setup_in_progress = False
        self.repository_status.configure(text=f"仓库已安全连接，但首次同步失败：{exc}\n配置已保留，检查网络后点击重试。")
        self.back_button.configure(state="normal")
        self.next_button.configure(text="重试首次同步")
        self._update_next_state()

    def _choose_directory(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(initialdir=variable.get() or str(Path.home()), parent=self)
        if selected:
            variable.set(selected)
