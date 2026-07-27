from __future__ import annotations

import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from typing import Any

from .core.onboarding import (
    GH_DOWNLOAD_URL,
    GIT_DOWNLOAD_URL,
    GITHUB_SIGNUP_URL,
    ConnectivityResult,
    RepositorySetupResult,
    check_github_connectivity,
    create_private_repository,
    detect_system_proxy,
    github_setup_status,
    launch_dependency_install,
    launch_github_login,
    validate_proxy_url,
)


class OnboardingWizard(tk.Toplevel):
    def __init__(self, app: Any):
        super().__init__(app)
        self.app = app
        self.title("首次配置向导")
        self.geometry("860x640")
        self.minsize(760, 580)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.step = 0
        self.network_ok = False
        self.account_status: dict[str, object] = {}
        self.pages: list[ttk.Frame] = []
        self.confirm_private = tk.BooleanVar(value=False)
        self.china_mode = tk.BooleanVar(value=app.settings.china_network_mode)
        self.proxy_url = tk.StringVar(value=app.settings.proxy_url)
        self.repository_name = tk.StringVar(value="codex-sync-vault")
        default_vault = app.settings.vault_path or str(Path.home() / "Documents" / "CodexSync" / "codex-sync-vault")
        self.local_path = tk.StringVar(value=default_vault)
        self.codex_home = tk.StringVar(value=app.settings.codex_home)
        self.device_name = tk.StringVar(value=app.settings.device_name)
        self.proxy_url.trace_add("write", lambda *_args: self._invalidate_network())
        self._build()
        self.grab_set()

    def _build(self) -> None:
        shell = ttk.Frame(self, padding=24)
        shell.pack(fill="both", expand=True)
        top = ttk.Frame(shell)
        top.pack(fill="x", pady=(0, 16))
        ttk.Label(top, text="首次配置", style="Title.TLabel").pack(side="left")
        self.progress = ttk.Label(top, text="步骤 1 / 4", style="Status.TLabel")
        self.progress.pack(side="right")
        self.page_host = ttk.Frame(shell, style="Panel.TFrame", padding=22)
        self.page_host.pack(fill="both", expand=True)
        for builder in (self._welcome_page, self._network_page, self._account_page, self._repository_page):
            page = ttk.Frame(self.page_host, style="Panel.TFrame")
            builder(page)
            self.pages.append(page)
        footer = ttk.Frame(shell)
        footer.pack(fill="x", pady=(16, 0))
        self.back_button = ttk.Button(footer, text="上一步", command=self._back)
        self.back_button.pack(side="left")
        ttk.Button(footer, text="稍后配置", command=self.destroy).pack(side="left", padx=8)
        self.next_button = ttk.Button(footer, text="下一步", style="Accent.TButton", command=self._next)
        self.next_button.pack(side="right")
        self._show_step()

    @staticmethod
    def _heading(parent: ttk.Frame, title: str, subtitle: str) -> None:
        ttk.Label(parent, text=title, style="PanelSection.TLabel").pack(anchor="w")
        ttk.Label(parent, text=subtitle, style="PanelMuted.TLabel", wraplength=720, justify="left").pack(anchor="w", pady=(6, 18))

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
        ttk.Checkbutton(
            page,
            text="我确认同步仓库必须保持私有，并理解会话文字可能包含敏感信息。",
            variable=self.confirm_private,
        ).pack(anchor="w", pady=(24, 0))

    def _network_page(self, page: ttk.Frame) -> None:
        self._heading(page, "检查 GitHub 网络连接", "中国大陆网络可能无法直接访问 GitHub。请先启动符合所在地法律和组织规定的代理工具，再填写本机 HTTP 代理地址。")
        ttk.Checkbutton(page, text="我位于中国大陆或当前网络需要代理", variable=self.china_mode).pack(anchor="w", pady=(0, 14))
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
        self._heading(page, "准备 GitHub 账号", "没有账号时先打开注册页面；已有账号时点击登录。GitHub 会在浏览器中要求你确认一次设备授权。")
        actions = ttk.Frame(page, style="Panel.TFrame")
        actions.pack(fill="x", pady=(0, 18))
        ttk.Button(actions, text="没有账号：打开注册", command=lambda: webbrowser.open(GITHUB_SIGNUP_URL)).pack(side="left")
        ttk.Button(actions, text="打开 GitHub 登录", style="Accent.TButton", command=self._launch_login).pack(side="left", padx=8)
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

    def _repository_page(self, page: ttk.Frame) -> None:
        self._heading(page, "自动创建私有仓库", "点击完成后，软件会创建私有仓库、克隆到本机、配置 Git 身份，并保存日常同步设置。")
        form = ttk.Frame(page, style="Panel.TFrame")
        form.pack(fill="x")
        fields = (
            ("GitHub 仓库名称", self.repository_name, False),
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
        self.repository_status = ttk.Label(page, text="仓库将通过 GitHub API 验证为私有后才会启用。", style="PanelMuted.TLabel")
        self.repository_status.pack(anchor="w", pady=(18, 0))

    def _show_step(self) -> None:
        for page in self.pages:
            page.pack_forget()
        self.pages[self.step].pack(fill="both", expand=True)
        self.progress.configure(text=f"步骤 {self.step + 1} / {len(self.pages)}")
        self.back_button.configure(state="normal" if self.step else "disabled")
        self.next_button.configure(text="自动创建并完成" if self.step == len(self.pages) - 1 else "下一步")
        if self.step == 2:
            self._refresh_account()

    def _back(self) -> None:
        if self.step:
            self.step -= 1
            self._show_step()

    def _next(self) -> None:
        if self.step == 0 and not self.confirm_private.get():
            messagebox.showwarning("需要确认", "请确认私有仓库和敏感信息提示后继续。", parent=self)
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
        self.network_status.configure(text="正在测试 GitHub API...")
        self.app._run_task("测试 GitHub 网络", lambda: check_github_connectivity(proxy), self._show_network_result, callback_with_result=True)

    def _show_network_result(self, result: ConnectivityResult) -> None:
        self.network_ok = result.ok
        if result.ok:
            mode = "通过代理" if result.proxy_used else "直接连接"
            self.network_status.configure(text=f"连接成功：{mode}，HTTP {result.status}")
        else:
            self.network_status.configure(text=f"连接失败：{result.reason}")

    def _launch_login(self) -> None:
        try:
            launch_github_login(self.app.store.app_home, self.proxy_url.get())
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法打开登录", str(exc), parent=self)
            return
        messagebox.showinfo("登录窗口已打开", "请在新终端和浏览器中完成 GitHub 授权，然后返回此向导点击“重新检测”。", parent=self)

    def _install_dependencies(self) -> None:
        if not messagebox.askyesno(
            "确认安装",
            "将打开系统终端安装 Git 和 GitHub CLI，可能请求管理员权限并占用约 300 MiB 磁盘。可以通过系统软件管理器卸载。是否继续？",
            parent=self,
        ):
            return
        try:
            launch_dependency_install(self.app.store.app_home, self.proxy_url.get())
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("无法自动安装", str(exc), parent=self)
            return
        messagebox.showinfo("安装窗口已打开", "请在终端中完成安装，然后重新打开本软件并点击“重新检测”。", parent=self)

    def _refresh_account(self) -> None:
        try:
            proxy = validate_proxy_url(self.proxy_url.get())
        except ValueError as exc:
            messagebox.showerror("代理地址错误", str(exc), parent=self)
            return
        self.app._run_task("检查 GitHub 登录", lambda: github_setup_status(proxy), self._show_account_status, callback_with_result=True)

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
        except (OSError, ValueError) as exc:
            messagebox.showerror("配置不完整", str(exc), parent=self)
            return
        self.repository_status.configure(text="正在创建并验证私有仓库...")
        self.app._run_task(
            "首次自动配置",
            lambda: create_private_repository(local_path, self.repository_name.get(), proxy),
            lambda result: self._complete(result, proxy, codex_home, device_name),
            callback_with_result=True,
        )

    def _complete(self, result: RepositorySetupResult, proxy: str, codex_home: Path, device_name: str) -> None:
        settings = self.app.settings
        settings.codex_home = str(codex_home)
        settings.vault_path = str(result.local_path)
        settings.vault_remote = result.url.rstrip("/") + ".git"
        settings.device_name = device_name
        settings.proxy_url = proxy
        settings.china_network_mode = self.china_mode.get()
        settings.onboarding_complete = True
        self.app.store.save(settings)
        for key, variable in self.app.setting_vars.items():
            if hasattr(settings, key):
                variable.set(str(getattr(settings, key)))
        self.destroy()
        self.app.refresh_all()
        self.app.show_page("sync")
        messagebox.showinfo("配置完成", f"私有仓库已创建：{result.owner}/{result.name}\n现在可以点击“导出并推送”。", parent=self.app)

    def _choose_directory(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(initialdir=variable.get() or str(Path.home()), parent=self)
        if selected:
            variable.set(selected)
