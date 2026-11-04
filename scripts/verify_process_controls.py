"""Exercise process-control UI using simulated processes; never terminate real apps."""
from pathlib import Path
from unittest.mock import Mock, patch
from codex_sync_desktop.app import CodexSyncApp
from codex_sync_desktop.core.config import SettingsStore
from codex_sync_desktop.core.processes import ProcessInfo, TerminationReport

root = Path('build/process-control-verification').resolve()
store = SettingsStore(root/'settings')
settings = store.load()
settings.codex_home = str(root/'fictional-codex')
settings.onboarding_complete = True
store.save(settings)
app = CodexSyncApp(store)
for task in app.tk.call('after', 'info'):
    app.after_cancel(task)
app.show_page('sync')
app.update_idletasks()
process = ProcessInfo(12345, 'ChatGPT')
try:
    with patch('codex_sync_desktop.app.running_codex_processes', return_value=[process]), \
         patch('codex_sync_desktop.app.terminate_related_processes') as terminate, \
         patch('codex_sync_desktop.app.messagebox.askyesno', return_value=False):
        app.exit_process_button.invoke()
        terminate.assert_not_called()
    report = TerminationReport(1, [], [])
    def run_task(label, work, callback, **kwargs):
        callback(work())
    app._run_task = run_task
    with patch('codex_sync_desktop.app.running_codex_processes', return_value=[process]), \
         patch('codex_sync_desktop.app.terminate_related_processes', return_value=report) as terminate, \
         patch('codex_sync_desktop.app.messagebox.askyesno', return_value=True), \
         patch('codex_sync_desktop.app.messagebox.showinfo') as info:
        app.exit_process_button.invoke()
        terminate.assert_called_once()
        info.assert_called_once()
    # A blocked import uses the same confirmation, without writing conversation data.
    app._require_vault = lambda: root/'fictional-vault'
    with patch('codex_sync_desktop.app.running_codex_processes', return_value=[process]), \
         patch.object(app, 'exit_related_processes') as offer, \
         patch('codex_sync_desktop.app.apply_import') as write:
        app.import_and_repair()
        offer.assert_called_once()
        write.assert_not_called()
    root.mkdir(parents=True,exist_ok=True)
    (root/'result.txt').write_text('passed: cancel, confirm, blocked import; real process termination was mocked\n')
finally:
    app.destroy()
