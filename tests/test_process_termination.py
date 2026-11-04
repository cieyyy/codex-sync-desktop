import signal
from unittest import TestCase
from unittest.mock import patch
from codex_sync_desktop.core.processes import ProcessInfo, _is_blocked, terminate_related_processes
from codex_sync_desktop.core.git_client import compact_failure_reason


class ProcessExitTests(TestCase):
    def test_only_related_executables_match(self):
        for value in ('/Applications/ChatGPT.app/Contents/Helpers/browser_crashpad_handler',
                      '/Applications/Codex.app/Contents/MacOS/Codex', 'ChatGPT.exe', 'Codex Helper (Renderer).exe', '/usr/local/bin/codex'):
            self.assertTrue(_is_blocked(value), value)
        for value in ('/Applications/Codex Sync Desktop.app/Contents/MacOS/Codex Sync Desktop',
                      'Codex Sync Desktop.exe', '/Applications/Chrome.app/Contents/MacOS/Chrome',
                      '/tmp/my-chatgpt-project/python', '/tmp/codex-backup', 'chatgpt-notes.exe'):
            self.assertFalse(_is_blocked(value), value)

    @patch('codex_sync_desktop.core.processes.platform.system', return_value='Darwin')
    @patch('codex_sync_desktop.core.processes.time.sleep')
    @patch('codex_sync_desktop.core.processes.os.kill')
    @patch('codex_sync_desktop.core.processes.running_codex_processes')
    def test_graceful_exit_never_sends_kill(self, scan, kill, _sleep, _platform):
        process = ProcessInfo(120, '/Applications/ChatGPT.app/Contents/MacOS/ChatGPT')
        scan.side_effect = [[process], [process], []]
        report = terminate_related_processes(900, grace_seconds=1)
        kill.assert_called_once_with(120, signal.SIGTERM)
        self.assertEqual(report.remaining, [])

    @patch('codex_sync_desktop.core.processes.platform.system', return_value='Darwin')
    @patch('codex_sync_desktop.core.processes.time.sleep')
    @patch('codex_sync_desktop.core.processes.os.kill')
    @patch('codex_sync_desktop.core.processes.running_codex_processes')
    def test_force_only_remaining_related_pids(self, scan, kill, _sleep, _platform):
        proc = ProcessInfo(120, 'ChatGPT')
        scan.side_effect = [[proc], [proc], [proc], [proc], []]
        report = terminate_related_processes(900, grace_seconds=0)
        self.assertEqual([c.args for c in kill.call_args_list], [(120, signal.SIGTERM), (120, signal.SIGKILL)])
        self.assertFalse(report.remaining)

    @patch('codex_sync_desktop.core.processes.time.sleep')
    @patch('codex_sync_desktop.core.processes.os.kill')
    @patch('codex_sync_desktop.core.processes.running_codex_processes')
    def test_reused_pid_and_own_pid_are_never_signalled(self, scan, kill, _sleep):
        proc = ProcessInfo(120, 'ChatGPT')
        scan.side_effect = [[proc, ProcessInfo(900, 'Codex')], [ProcessInfo(120, 'other')], [], []]
        terminate_related_processes(900, grace_seconds=0)
        kill.assert_not_called()

    @patch('codex_sync_desktop.core.processes.platform.system', return_value='Darwin')
    @patch('codex_sync_desktop.core.processes.time.sleep')
    @patch('codex_sync_desktop.core.processes.os.kill', side_effect=PermissionError('denied'))
    @patch('codex_sync_desktop.core.processes.running_codex_processes')
    def test_permission_failure_reports_remaining(self, scan, _kill, _sleep, _platform):
        proc = ProcessInfo(120, 'ChatGPT')
        scan.return_value = [proc]
        report = terminate_related_processes(900, grace_seconds=0)
        self.assertEqual(report.remaining, [proc])
        self.assertTrue(report.errors)

    @patch('codex_sync_desktop.core.processes.os.kill')
    @patch('codex_sync_desktop.core.processes.running_codex_processes', side_effect=RuntimeError('scan failed'))
    def test_scan_failure_never_signals(self, _scan, kill):
        with self.assertRaises(RuntimeError):
            terminate_related_processes(900)
        kill.assert_not_called()

    @patch('codex_sync_desktop.core.processes.platform.system', return_value='Windows')
    @patch('codex_sync_desktop.core.processes.time.sleep')
    @patch('codex_sync_desktop.core.processes.subprocess.run')
    @patch('codex_sync_desktop.core.processes.running_codex_processes')
    def test_windows_uses_exact_pid_without_broad_tree_kill(self, scan, run, _sleep, _platform):
        proc = ProcessInfo(120, 'ChatGPT.exe')
        scan.side_effect = [[proc], [proc], [proc], [proc], []]
        run.return_value.returncode = 0
        terminate_related_processes(900, grace_seconds=0)
        self.assertEqual([c.args[0] for c in run.call_args_list], [['taskkill','/PID','120'], ['taskkill','/PID','120','/F']])

    def test_detached_head_error_explains_cause(self):
        error = 'You are not currently on a branch.\nPlease specify which branch you want to rebase against.\n git pull <remote> <branch>'
        self.assertIn('HEAD', compact_failure_reason(error))
        self.assertNotEqual(compact_failure_reason(error), 'git pull <remote> <branch>')

    def test_unfinished_rebase_is_not_restarted(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from codex_sync_desktop.core.git_client import VaultGit
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'.git/rebase-merge').mkdir(parents=True)
            with patch('codex_sync_desktop.core.git_client.run') as run:
                result = VaultGit(root).pull()
            self.assertFalse(result.ok)
            self.assertIn('rebase', compact_failure_reason(result.output))
            run.assert_not_called()
