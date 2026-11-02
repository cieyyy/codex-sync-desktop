import json, subprocess
from pathlib import Path
from codex_sync_desktop.app import CodexSyncApp
from codex_sync_desktop.core.config import SettingsStore
from codex_sync_desktop.core.models import ImportItem, ImportPlan
from codex_sync_desktop.wizard import OnboardingWizard
from codex_sync_desktop.ui_theme import COLORS
root=Path('build/studio-verification').resolve();root.mkdir(parents=True,exist_ok=True)
store=SettingsStore(root/'settings')
settings=store.load();settings.appearance='dark';settings.codex_home=str(root/'fictional-codex');settings.onboarding_complete=True
store.save(settings)
app=CodexSyncApp(store)
for task in app.tk.call('after','info'): app.after_cancel(task)
app.settings.codex_home=str(root/'fictional-codex');app.settings.onboarding_complete=True
app.report_callback_exception=lambda *args: (_ for _ in ()).throw(args[1])
app.attributes('-topmost',True);app.geometry('1280x840+30+30');app.update()
app._update_studio_overview({'git':True,'vault_exists':False,'sessions':0})
def capture(name, window=None):
 window=window or app
 app.update();app.after(250);rect=f'{window.winfo_rootx()},{window.winfo_rooty()},{window.winfo_width()},{window.winfo_height()}'
 subprocess.run(['screencapture','-x','-R'+rect,str(root/name)],check=True)
capture('overview.png')
records=[{'type':'event_msg','timestamp':'2026-11-02T10:00:00+08:00','payload':{'type':'user_message','message':'请整理模型测试的结果，生成一份报告。'}},{'type':'response_item','timestamp':'2026-11-02T10:00:08+08:00','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'已整理测试结果。报告包含请求记录、模型名称和性能指标。\n\n接下来核对数据来源，再生成汇总。'}]}}]
data=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records).encode()
project={'group_id':'local:models','name':'模型测试','status':'confirmed','roots':['/example/models']}
items=[ImportItem('copy',f'{i}.jsonl',root/'none',root/'none',incoming_content=data,task_id=str(i),source_title=title,project=project) for i,title in enumerate(['整理模型测试结果并生成报告','核对接口请求与模型映射','补充模型响应时间指标'])]
items.append(ImportItem('skipped-existing','protected.jsonl',root/'none',root/'none',task_id='protected',local_title='本机原始标题',incoming_content=data,project=project))
plan=ImportPlan('all',items,source_label='全部会话')
app.show_page('sync');app._show_import_plan(plan);app.update()
pane=app.preview_pane
assert pane.current_item is items[0]
pane.title_var.set('模型测试报告整理');app._render_studio_plan('skipped-existing');app.update()
assert app.title_overrides['all']['0']=='模型测试报告整理'
assert str(app.preview_pane.title_entry.cget('state'))=='disabled'
app._render_studio_plan('copy');pane=app.preview_pane
pane.search_var.set('NO_MATCH');app.update();assert pane.current_item is None
assert pane.title_var.get()==''
assert not pane.current_versions and pane.version_var.get()==''
pane.search_var.set('');app.update();assert pane.current_item is not None
assert '你' in pane.preview_text.get('1.0','end')
capture('sync-1280.png')
for width,height in [(1120,760),(920,640)]:
 app.geometry(f'{width}x{height}');app.update()
 assert pane.preview_text.winfo_width()>180
 print(width, 'preview height',pane.preview_text.winfo_height())
 assert pane.preview_text.winfo_height()>=100
 assert app.import_button.winfo_rooty()+app.import_button.winfo_height()<=app.winfo_rooty()+app.winfo_height()
 capture(f'sync-{width}.png')
app.sync_time_var.set('自定义日期');app._time_filter_changed();app._show_import_plan(plan)
app.sync_start_var.set('2026-10-01');app.update()
assert app.active_plan is None and app.preview_pane is None
app.show_page('backups');app.update();capture('backups.png')
app.show_page('maintenance');app.update();capture('settings.png')
app.geometry('1280x840');app.show_page('sync');app._show_import_plan(plan);app.update()
pane=app.preview_pane;pane.title_var.set('主题切换保留未保存标题')
app._set_task_state('正在拉取私有仓库最新内容',active=True);app.update()
started=app.task_activity.started
app._set_task_state('正在检查可导入会话',active=True)
assert app.task_activity.started == started
assert app.task_activity.bar.winfo_ismapped()
capture('progress-dark.png')
for theme in ('浅色','深色','浅色'):
 app.appearance_var.set(theme);app.change_appearance();app.update()
 assert pane.title_var.get()=='主题切换保留未保存标题'
 assert pane.preview_text.cget('background')==COLORS['surface_alt']
 assert str(pane.preview_text.tag_cget('assistant_header','foreground'))==COLORS['success']
 assert app.chrome.body.cget('background')==COLORS['background']
 assert app.store.load().appearance==('light' if theme=='浅色' else 'dark')
capture('progress-light.png')
app.geometry('920x640');app.update()
assert app.import_button.winfo_ismapped()
assert pane.preview_text.winfo_height()>=35
capture('progress-920.png')
app.geometry('1280x840');app.update()
app._set_task_state('检查会话 · 已完成',active=False);app.update()
assert app.task_activity.timer is None
assert not app.task_activity.bar.winfo_ismapped()
app._set_task_state('同步失败，请查看错误详情',active=False,failed=True)
assert app.task_activity.label.cget('style')=='TaskError.TLabel'
app._set_task_state('检查会话 · 已完成',active=False)
app.show_page('overview');capture('overview-light.png')
app.overview_tree.delete(*app.overview_tree.get_children())
for values in [('Codex 数据目录','正常','/example/.codex'),('本机会话','23','JSONL 会话文件'),('状态数据库','3','codex-dev.db, codex.db, state_5.sqlite'),('侧栏索引','正常','session_index.jsonl'),('Git','正常','Git 可用'),('GitHub CLI','已登录','认证可用'),('相关进程','4','/example/long-path/'+'project-folder/'*12)]:
 app.overview_tree.insert('','end',values=values)
app._toggle_diagnostics();popup=app.diagnostic_popup;popup.attributes('-topmost',True);app.update();capture('diagnostics-light.png',popup)
app.appearance_var.set('深色');app.change_appearance();app.update();capture('diagnostics-dark.png',popup)
popup.destroy()
wizard=OnboardingWizard(app)
wizard.repositories_loaded=True
wizard.repository_reference.set('example/private-vault')
wizard.local_path.set('/example/sync-vault');wizard.codex_home.set('/example/.codex');wizard.device_name.set('验证设备')
wizard.step=3;wizard._show_step();wizard.attributes('-topmost',True);app.update()
def radio_widgets(widget):
 result=[]
 for child in widget.winfo_children():
  if child.winfo_class()=='TRadiobutton':result.append(child)
  result.extend(radio_widgets(child))
 return result
choices=radio_widgets(wizard.pages[3]);assert len(choices)==2
choices[1].invoke();app.update();assert wizard.repository_mode.get()=='existing'
assert wizard.existing_repository_frame.winfo_ismapped()
choices[0].invoke();app.update();assert wizard.repository_mode.get()=='create'
choices[1].invoke()
wizard.set_task_state('正在读取私有仓库',active=True)
capture('wizard-dark.png',wizard)
wizard.geometry('700x500');app.update();assert wizard.next_button.winfo_rooty()+wizard.next_button.winfo_height()<=wizard.winfo_rooty()+wizard.winfo_height()
capture('wizard-700.png',wizard)
wizard.set_task_state('仓库读取完成',active=False);assert wizard.activity.timer is None
wizard.destroy()
(root/'result.json').write_text(json.dumps({'status':'passed','checks':['inline preview','title persistence','protected title readonly','empty search and recovery','dialogue mode','1280/1120/920 layout','date invalidation','backup/settings pages','theme persistence and repeated switching','unsaved input retention','task stage timer and success/failure','920 active task layout','700 wizard layout','repository segmented choices','diagnostic row and column dividers'],'fixture':'fictional; no real Codex import'},ensure_ascii=False,indent=2))
app.destroy()
