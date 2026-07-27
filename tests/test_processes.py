from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from codex_sync_desktop.core.processes import running_codex_processes


class RunningProcessesTests(TestCase):
    @patch("codex_sync_desktop.core.processes.subprocess.run")
    @patch("codex_sync_desktop.core.processes.platform.system", return_value="Windows")
    def test_missing_tasklist_output_is_empty(self, _mocked_system, mocked_run) -> None:
        mocked_run.return_value = SimpleNamespace(stdout=None, returncode=0)

        self.assertEqual(running_codex_processes(), [])

    @patch("codex_sync_desktop.core.processes.subprocess.run")
    @patch("codex_sync_desktop.core.processes.platform.system", return_value="Windows")
    def test_current_process_is_excluded(self, _mocked_system, mocked_run) -> None:
        mocked_run.return_value = SimpleNamespace(
            stdout='"Codex Sync Desktop.exe","42","Console","1","10,000 K"\n',
            returncode=0,
        )

        self.assertEqual(running_codex_processes(current_pid=42), [])
