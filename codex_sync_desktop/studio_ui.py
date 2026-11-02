"""The approved Sync Studio workspace, backed by real sync plans and diagnostics."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from pathlib import Path

from . import __version__
from .core.backups import list_backup_records
from .core.time_filter import TIME_FILTER_OPTIONS
from .core.import_preview import items_for_category
from .import_preview_dialog import ImportPreviewPane
from .ui_theme import COLORS
from .task_activity import TaskActivity
from .diagnostic_table import DiagnosticTable
from .window_chrome import bundled_asset_path, draw_sync_mark


def apply_studio_styles(app):
    style = ttk.Style(app)
    body = ('Helvetica Neue', 12) if app.tk.call('tk', 'windowingsystem') == 'aqua' else ('Segoe UI', 10)
    app.option_add('*Font', body)
    app.option_add('*TCombobox*Listbox.background', COLORS['surface'])
    app.option_add('*TCombobox*Listbox.foreground', COLORS['text'])
    app.option_add('*TCombobox*Listbox.selectBackground', COLORS['selection'])
    for name in ('TButton','Accent.TButton','Danger.TButton','Nav.TButton','NavActive.TButton','Quiet.TButton'):
        style.layout(name, [('Button.padding', {'sticky':'nswe', 'children':[('Button.label', {'sticky':'nswe'})]})])
    style.configure('TButton', background=COLORS['surface_alt'], foreground=COLORS['text'], padding=(12,9), borderwidth=0)
    style.map('TButton', background=[('disabled',COLORS['button_disabled']),('pressed',COLORS['selection']),('active',COLORS['surface'])], foreground=[('disabled',COLORS['text_disabled']),('!disabled',COLORS['text'])])
    style.configure('Quiet.TButton', background=COLORS['background'], foreground=COLORS['text_muted'], padding=(8,8))
    style.map('Quiet.TButton', background=[('active',COLORS['surface_alt'])], foreground=[('active',COLORS['text']),('!disabled',COLORS['text_muted'])])
    style.configure('Detail.TButton', background=COLORS['surface'], foreground=COLORS['text_muted'],padding=(4,2))
    style.configure('Accent.TButton', background=COLORS['primary'], foreground=COLORS['accent_ink'], padding=(16,10))
    style.map('Accent.TButton', foreground=[('disabled',COLORS['text_disabled']),('!disabled',COLORS['accent_ink'])])
    style.configure('Danger.TButton', background=COLORS['surface_alt'], foreground=COLORS['danger'])
    style.map('Danger.TButton', background=[('active',COLORS['surface'])], foreground=[('!disabled',COLORS['danger'])])
    style.configure('Nav.TButton', background=COLORS['sidebar'], foreground=COLORS['text_muted'], padding=(16,13), anchor='w')
    style.configure('NavActive.TButton', background=COLORS['selection'], foreground=COLORS['primary'], padding=(16,13), anchor='w')
    style.map('NavActive.TButton', background=[('active',COLORS['selection'])], foreground=[('!disabled',COLORS['primary'])])
    for name in ('Section.TLabel','PanelSection.TLabel'):
        style.configure(name, foreground=COLORS['text'],font=(body[0],13,'bold'))
    style.configure('Title.TLabel',font=(body[0],23,'bold'))
    style.configure('Hero.TLabel', background=COLORS['surface'],foreground=COLORS['text'],font=(body[0],21,'bold'))
    style.configure('Success.TLabel',background=COLORS['surface'],foreground=COLORS['success'],font=body)
    style.configure('SidebarMuted.TLabel', foreground=COLORS['text_muted'])
    style.configure('Brand.TLabel',background=COLORS['sidebar'],foreground=COLORS['text'],font=(body[0],17,'bold'))
    style.configure('Treeview',background=COLORS['background'],fieldbackground=COLORS['background'],borderwidth=0,rowheight=40)
    style.layout('Treeview',[('Treeview.treearea',{'sticky':'nswe'})])
    style.map('Treeview',background=[('selected',COLORS['selection'])])
    style.configure('Treeview.Heading',background=COLORS['background'],foreground=COLORS['text_muted'],font=body,relief='flat',padding=(8,10),borderwidth=0)
    style.layout('Treeview.Heading',[('Treeheading.padding',{'sticky':'nswe','children':[('Treeheading.text',{'sticky':'we'})]})])
    style.map('Treeview.Heading',background=[('active',COLORS['surface'])])
    for name in ('TEntry','TCombobox'):
        style.configure(name,fieldbackground=COLORS['background'],background=COLORS['surface_alt'],bordercolor=COLORS['border'],lightcolor=COLORS['border'],darkcolor=COLORS['border'],borderwidth=1)
    style.map('TCombobox',fieldbackground=[('readonly',COLORS['background'])],selectbackground=[('readonly',COLORS['background'])])
    style.configure('Status.TEntry',fieldbackground=COLORS['sidebar'],foreground=COLORS['text_muted'],borderwidth=0,padding=(6,5))
    style.map('Status.TEntry',foreground=[('readonly',COLORS['text_muted'])],fieldbackground=[('readonly',COLORS['sidebar'])])
    style.configure('Horizontal.TSeparator',background=COLORS['border'])
    style.configure('Task.TLabel',background=COLORS['surface'],foreground=COLORS['primary'],font=(body[0],12,'bold'))
    style.configure('TaskError.TLabel',background=COLORS['surface'],foreground=COLORS['danger'],font=(body[0],12,'bold'))
    style.configure('Task.Horizontal.TProgressbar',troughcolor=COLORS['border'],background=COLORS['primary'],lightcolor=COLORS['primary'],darkcolor=COLORS['primary'],bordercolor=COLORS['border'],borderwidth=0,thickness=8)
    style.layout('Segment.TRadiobutton', [('Radiobutton.padding', {'sticky':'nswe','children':[
        ('Radiobutton.focus', {'sticky':'nswe','children':[('Radiobutton.label',{'sticky':'nswe'})]})]})])
    style.configure('Segment.TRadiobutton',background=COLORS['surface_alt'],foreground=COLORS['text_muted'],padding=(16,11),focuscolor=COLORS['primary'],font=body)
    style.map('Segment.TRadiobutton',background=[('disabled',COLORS['button_disabled']),('selected',COLORS['selection']),('active',COLORS['secondary_hover'])],foreground=[('disabled',COLORS['text_disabled']),('selected',COLORS['primary']),('!disabled',COLORS['text_muted'])])
    for name in ('Vertical.TScrollbar','Horizontal.TScrollbar','Status.Horizontal.TScrollbar','Wizard.Vertical.TScrollbar'):
        style.configure(name,background=COLORS['surface_alt'],troughcolor=COLORS['background'],arrowcolor=COLORS['text_muted'],borderwidth=0,arrowsize=12)


class StudioUI:
    def _build_ui(self):
        shell = ttk.Frame(self.chrome.body)
        shell.pack(fill='both',expand=True)
        shell.rowconfigure(0,weight=1)
        shell.columnconfigure(1,weight=1)
        sidebar = ttk.Frame(shell,style='Sidebar.TFrame',padding=(14,28,14,12),width=205)
        sidebar.grid(row=0,column=0,sticky='nsew')
        sidebar.grid_propagate(False)
        brand = ttk.Frame(sidebar,style='Sidebar.TFrame')
        brand.pack(fill='x',pady=(8,30))
        try:
            from PIL import Image,ImageTk
            self.brand_image = ImageTk.PhotoImage(Image.open(bundled_asset_path('icon.png')).resize((38,38)))
            tk.Label(brand,image=self.brand_image,bg=COLORS['sidebar'],borderwidth=0).pack(side='left',padx=(0,10))
        except (ImportError,OSError):
            canvas=tk.Canvas(brand,width=36,height=36,bg=COLORS['sidebar'],highlightthickness=0)
            canvas.pack(side='left',padx=(0,10));draw_sync_mark(canvas,36)
        brand_text=ttk.Frame(brand,style='Sidebar.TFrame');brand_text.pack(side='left')
        ttk.Label(brand_text,text='Codex Sync',style='Brand.TLabel').pack(anchor='w')
        ttk.Label(sidebar,text='让工作在设备间接续',style='SidebarMuted.TLabel').pack(anchor='w',padx=8,pady=(0,18))
        for key,title in (('overview','概览'),('sync','同步与导入'),('backups','备份与撤销')):
            button=ttk.Button(sidebar,text=title,style='Nav.TButton',command=lambda value=key:self.show_page(value))
            button.pack(fill='x',pady=3);self.nav_buttons[key]=button
        ttk.Label(sidebar,text=f'Codex Sync Desktop  {__version__}',style='SidebarMuted.TLabel',wraplength=175).pack(side='bottom',anchor='w',padx=8,pady=(20,4))
        button=ttk.Button(sidebar,text='设置与诊断',style='Nav.TButton',command=lambda:self.show_page('maintenance'))
        button.pack(side='bottom',fill='x',pady=(12,0));self.nav_buttons['maintenance']=button
        ttk.Separator(sidebar).pack(side='bottom',fill='x',pady=(14,0))
        self.repo_label=ttk.Label(sidebar,text=self.settings.vault.name if self.settings.vault else '尚未配置仓库',style='SidebarMuted.TLabel',wraplength=175)
        self.repo_label.pack(side='bottom',anchor='w',padx=8,pady=(12,0))
        main=ttk.Frame(shell)
        main.grid(row=0,column=1,sticky='nsew')
        top=ttk.Frame(main,padding=(26,12))
        top.pack(fill='x')
        self.page_label=ttk.Label(top,text='工作区 / 概览',style='Muted.TLabel');self.page_label.pack(side='left')
        self.appearance_var=tk.StringVar(value='浅色' if self.settings.appearance=='light' else '深色')
        theme=ttk.Combobox(top,textvariable=self.appearance_var,values=('深色','浅色'),width=5,state='readonly',takefocus=True)
        theme.pack(side='right',padx=(14,0));theme.bind('<<ComboboxSelected>>',lambda _event:self.change_appearance())
        ttk.Label(top,text='外观',style='Muted.TLabel').pack(side='right',padx=(14,0))
        self.connection_label=ttk.Label(top,text='正在检查',style='Muted.TLabel');self.connection_label.pack(side='right')
        ttk.Separator(main).pack(fill='x')
        self.task_activity=TaskActivity(main)
        self.content=ttk.Frame(main,padding=(22,14,22,12));self.content.pack(fill='both',expand=True)
        for key in ('overview','sync','backups','maintenance'):
            self.pages[key]=ttk.Frame(self.content)
        self.overview_tab,self.sync_tab,self.backups_tab,self.maintenance_tab=(self.pages[key] for key in ('overview','sync','backups','maintenance'))
        footer=ttk.Frame(self.chrome.body,style='Sidebar.TFrame',padding=(12,3));footer.pack(side='bottom',fill='x',before=shell)
        self.busy_text=tk.StringVar(value='就绪')
        self.busy_label=ttk.Entry(footer,textvariable=self.busy_text,state='readonly',style='Status.TEntry',takefocus=False)
        self.busy_label.pack(side='left',fill='x',expand=True)
        ttk.Label(footer,text='仅新增 · 本机会话保护已启用',style='SidebarMuted.TLabel').pack(side='right',padx=10)
        self._build_overview();self._build_sync();self._build_backups();self._build_maintenance()
        self.show_page('overview')

    def _build_overview(self):
        head=ttk.Frame(self.overview_tab);head.pack(fill='x',pady=(0,8))
        copy=ttk.Frame(head);copy.pack(side='left',fill='x',expand=True)
        self._page_header(copy,'同步概览','你的会话、项目与工作目录，都有各自的位置。')
        self._task_button(head,'刷新状态',self.refresh_all).pack(side='right',anchor='n')
        columns=ttk.Frame(self.overview_tab);columns.pack(fill='both',expand=True)
        columns.columnconfigure(0,weight=1);columns.columnconfigure(1,weight=0,minsize=225);columns.rowconfigure(0,weight=1)
        left=ttk.Frame(columns);left.grid(row=0,column=0,sticky='nsew',padx=(0,24))
        self.ready_panel=ttk.Frame(left,style='Panel.TFrame',padding=22);self.ready_panel.pack(fill='x')
        self.ready_status=ttk.Label(self.ready_panel,text='正在读取同步环境',style='Success.TLabel');self.ready_status.pack(anchor='w')
        self.ready_title=ttk.Label(self.ready_panel,text='把需要的会话，带到这台电脑。',style='Hero.TLabel',wraplength=520);self.ready_title.pack(anchor='w',pady=(15,10))
        self.ready_copy=ttk.Label(self.ready_panel,text='先核对会话与导入范围，再开始同步。已有会话保留原样。',style='PanelMuted.TLabel',wraplength=520);self.ready_copy.pack(anchor='w',pady=(0,16))
        self.ready_panel.bind('<Configure>',lambda event:[widget.configure(wraplength=max(220,event.width-44)) for widget in (self.ready_title,self.ready_copy)],add='+')
        self._task_button(self.ready_panel,'查看可导入会话',self._inspect_from_overview,'Accent.TButton').pack(anchor='w')
        route=ttk.Frame(left,padding=(0,20));route.pack(fill='x')
        self.local_count_label=ttk.Label(route,text='本机 Codex  ·  检查中',style='Muted.TLabel');self.local_count_label.pack(side='left')
        self.remote_count_label=ttk.Label(route,text='同步仓库  ·  待检查',style='Muted.TLabel');self.remote_count_label.pack(side='right')
        ttk.Separator(left).pack(fill='x')
        recent_head=ttk.Frame(left);recent_head.pack(fill='x',pady=(20,12))
        ttk.Label(recent_head,text='最近的导入与备份',style='Section.TLabel').pack(side='left')
        ttk.Button(recent_head,text='查看备份',style='Quiet.TButton',command=lambda:self.show_page('backups')).pack(side='right')
        self.recent_tree=ttk.Treeview(left,columns=('action','status','time'),show='headings',height=4)
        for name,title,width in (('action','操作',150),('status','结果',90),('time','时间',120)):
            self.recent_tree.heading(name,text=title);self.recent_tree.column(name,width=width,minwidth=65)
        self.recent_tree.pack(fill='both',expand=True)
        self.recent_empty=ttk.Label(left,text='尚无导入记录。完成导入后，可在这里查看最近一次撤销点。',style='Muted.TLabel',wraplength=400)
        self.recent_empty.pack(anchor='w',pady=10)
        side=ttk.Frame(columns);side.grid(row=0,column=1,sticky='nsew')
        ttk.Label(side,text='连接与保护',style='Section.TLabel').pack(anchor='w',pady=(0,18))
        ttk.Label(side,text='同步仓库',style='Muted.TLabel').pack(anchor='w')
        self.overview_repo=ttk.Label(side,text='尚未配置',wraplength=220);self.overview_repo.pack(anchor='w',pady=(6,18))
        ttk.Label(side,text='本机工作区',style='Muted.TLabel').pack(anchor='w')
        ttk.Label(side,text='Codex 数据目录').pack(anchor='w',pady=(6,3))
        ttk.Button(side,text='打开本机目录',style='Quiet.TButton',command=lambda:self._open_path(self.settings.codex_path)).pack(anchor='w',pady=(0,18))
        ttk.Separator(side).pack(fill='x',pady=(0,18))
        ttk.Label(side,text='本机会话保护已启用',style='Section.TLabel').pack(anchor='w',pady=(0,10))
        ttk.Label(side,text='保留原有标题与会话正文\n保留项目归属与工作目录\n只导入本机缺少的会话',style='Muted.TLabel',justify='left').pack(anchor='w',pady=(0,18))
        ttk.Separator(side).pack(fill='x')
        self.diagnostic_toggle=ttk.Button(side,text='展开环境检查',style='Quiet.TButton',command=self._toggle_diagnostics);self.diagnostic_toggle.pack(anchor='w',pady=(14,4))
        ttk.Button(side,text='打开设置与诊断',style='Quiet.TButton',command=lambda:self.show_page('maintenance')).pack(anchor='w')
        self.diagnostics_holder=ttk.Frame(self.overview_tab)
        self.overview_tree=self._tree(self.diagnostics_holder,('item','status','detail'),(170,90,480))

    def _toggle_diagnostics(self):
        if hasattr(self,'diagnostic_popup') and self.diagnostic_popup.winfo_exists():
            self.diagnostic_popup.lift();return
        self.diagnostic_popup=tk.Toplevel(self)
        self.diagnostic_popup.title('环境检查')
        self.diagnostic_popup.configure(background=COLORS['background'])
        frame=ttk.Frame(self.diagnostic_popup,padding=20);frame.pack(fill='both',expand=True)
        self._page_header(frame,'环境检查','逐项查看本机环境，详情支持自动换行。')
        rows=[self.overview_tree.item(iid,'values') for iid in self.overview_tree.get_children()]
        table=DiagnosticTable(frame,rows);table.pack(fill='both',expand=True,pady=(8,0))
        self.diagnostic_popup.geometry('860x620');self.diagnostic_popup.minsize(640,400)

    def _inspect_from_overview(self):
        self.show_page('sync');self.preview_import()

    def _update_studio_overview(self, diagnostics):
        ready=bool(diagnostics.get('vault_exists') and diagnostics.get('git'))
        self.connection_label.configure(text='仓库已配置' if ready else '需要配置')
        self.ready_status.configure(text='同步仓库已就绪，可以检查可导入会话' if ready else '完成配置后，即可检查和同步会话')
        self.local_count_label.configure(text=f"本机 Codex  ·  {diagnostics.get('sessions',0)} 个会话文件")
        vault=self.settings.vault
        self.overview_repo.configure(text=self.settings.vault_remote or (vault.name if vault else '尚未配置同步仓库'))
        self.repo_label.configure(text=vault.name if vault else '尚未配置仓库')
        if self.active_plan is not None:
            self.ready_title.configure(text=f"{self.active_plan.counts.get('copy',0)} 个新会话，等待导入。")
        elif ready:
            self.ready_title.configure(text='查看有哪些会话，可以继续处理。')
        else:
            self.ready_title.configure(text='连接你的同步仓库。')
        self.recent_tree.delete(*self.recent_tree.get_children())
        records=list_backup_records(self.settings.codex_path)[:4]
        for record in records:
            self.recent_tree.insert('', 'end', values=(record['kind'],{'completed':'已完成','rolled_back':'已撤销','failed':'失败'}.get(record['status'],'已保存'),str(record['created'])[:16]))
        if records:
            self.recent_empty.pack_forget()
            self.recent_tree.pack(fill='both',expand=True)
        else:
            self.recent_tree.pack_forget()
            self.recent_empty.pack(anchor='w',pady=10)

    def _build_sync(self):
        head=ttk.Frame(self.sync_tab);head.pack(fill='x',pady=(0,16))
        copy=ttk.Frame(head);copy.pack(side='left',fill='x',expand=True)
        self._page_header(copy,'同步与导入','选好要继续的会话，再带到这台电脑上。')
        self._task_button(head,'重新检查',self.preview_import).pack(side='right',anchor='n',padx=(8,0))
        self._task_button(head,'上传本机会话',self.export_and_push).pack(side='right',anchor='n')
        filters=ttk.Frame(self.sync_tab);filters.pack(fill='x',pady=(0,10))
        ttk.Label(filters,text='导入时间',style='Muted.TLabel').pack(side='left',padx=(0,8))
        self.sync_time_var=tk.StringVar(value=self.settings.sync_time_mode)
        self.sync_start_var=tk.StringVar(value=self.settings.sync_start_date)
        self.sync_end_var=tk.StringVar(value=self.settings.sync_end_date)
        combo=ttk.Combobox(filters,textvariable=self.sync_time_var,values=TIME_FILTER_OPTIONS,state='readonly',width=13);combo.pack(side='left')
        self.date_fields=ttk.Frame(filters)
        self.sync_start_entry=ttk.Entry(self.date_fields,textvariable=self.sync_start_var,width=11);self.sync_start_entry.pack(side='left')
        ttk.Label(self.date_fields,text=' 至 ',style='Muted.TLabel').pack(side='left')
        self.sync_end_entry=ttk.Entry(self.date_fields,textvariable=self.sync_end_var,width=11);self.sync_end_entry.pack(side='left')
        combo.bind('<<ComboboxSelected>>',lambda _event:self._time_filter_changed())
        self.source_count_label=ttk.Label(filters,text='仓库会话：—',style='Muted.TLabel');self.source_count_label.pack(side='right')
        self.source_time_label=ttk.Label(self.sync_tab,text='最后上传：—',style='Muted.TLabel')
        ttk.Label(self.sync_tab,text='只导入本机缺少的会话 · 保留已有标题、项目与工作目录',style='Muted.TLabel').pack(anchor='w',pady=(0,8))
        footer=ttk.Frame(self.sync_tab);footer.pack(side='bottom',fill='x',pady=(14,0))
        self.import_summary=ttk.Label(footer,text='先检查会话，再核对导入范围。',style='Muted.TLabel');self.import_summary.pack(side='left')
        self.import_button=self._task_button(footer,'导入会话',self.import_and_repair,'Accent.TButton');self.import_button.pack(side='right')
        self._task_button(footer,'一键同步',self.sync_once).pack(side='right',padx=8)
        ttk.Label(self.sync_tab,text='预览无需退出 Codex；正式导入前需退出相关程序，并自动保留一次撤销点。',style='Muted.TLabel').pack(side='bottom',anchor='w',pady=(8,0))
        self.category_bar=ttk.Frame(self.sync_tab);self.category_bar.pack(fill='x',pady=(0,8))
        self.category_buttons={}
        for key,title in (('copy','可导入'),('skipped-existing','本机已保护'),('skipped-time','按时间跳过'),('failure','校验失败')):
            button=ttk.Button(self.category_bar,text=title+'  —',style='Quiet.TButton',command=lambda value=key:self._render_studio_plan(value))
            button.pack(side='left',padx=(0,8));self.category_buttons[key]=button
        self.workspace=ttk.Frame(self.sync_tab);self.workspace.pack(fill='both',expand=True)
        self.preview_pane=None
        empty=ttk.Frame(self.workspace,style='Panel.TFrame',padding=24);empty.pack(fill='both',expand=True)
        ttk.Label(empty,text='把需要的工作，带到这里。',style='PanelSection.TLabel').pack(anchor='w',pady=(10,12))
        ttk.Label(empty,text='检查仓库后，会话列表和对话预览会显示在这里。\n可以按项目、活动时间和标题筛选，核对后再导入。',style='PanelMuted.TLabel').pack(anchor='w',pady=(0,20))
        self._task_button(empty,'检查可导入会话',self.preview_import,'Accent.TButton').pack(anchor='w')
        self.import_tree=ttk.Treeview(self.sync_tab,columns=('action','count','meaning'),show='headings')
        self._time_filter_changed()
        self.sync_start_var.trace_add('write',lambda *_:self._time_filter_changed())
        self.sync_end_var.trace_add('write',lambda *_:self._time_filter_changed())

    def _render_studio_plan(self, category='copy'):
        if self.active_plan is None:return
        if self.preview_pane is not None and not self.preview_pane._commit_title(show_feedback=True):return
        for child in self.workspace.winfo_children():child.destroy()
        self.task_buttons=[button for button in self.task_buttons if button.winfo_exists()]
        for key,button in self.category_buttons.items():
            count=len(items_for_category(self.active_plan,key))
            title={'copy':'可导入','skipped-existing':'本机已保护','skipped-time':'按时间跳过','failure':'校验失败'}[key]
            button.configure(text=f'{title}  {count}',style='NavActive.TButton' if key==category else 'Quiet.TButton')
        overrides=self.title_overrides.setdefault(self.active_plan.source_device,{})
        self.preview_pane=ImportPreviewPane(self.workspace,self.active_plan,category,overrides,self._remember_title_override)
        self.preview_pane.pack(fill='both',expand=True)
        count=self.active_plan.counts.get('copy',0)
        self.import_button.configure(text=f'导入 {count} 个会话')
        self.import_summary.configure(text=f'将新增 {count} 个会话，已有会话保持原样。')
        self.ready_title.configure(text=f'{count} 个新会话，等待导入。')
