import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from codex_sync_desktop.core.sessions import NoActiveSessionsError
from codex_sync_desktop.wizard import OnboardingWizard


class WizardWorkflowTests(TestCase):
    @patch("codex_sync_desktop.wizard.messagebox.showinfo")
    def test_unchecked_private_confirmation_is_checked_and_advances(self, showinfo):
        confirmation = Mock()
        confirmation.get.return_value = False
        wizard = SimpleNamespace(
            step=0,
            pages=[object(), object(), object(), object()],
            confirm_private=confirmation,
            _show_step=Mock(),
        )

        OnboardingWizard._next(wizard)

        confirmation.set.assert_called_once_with(True)
        self.assertEqual(wizard.step, 1)
        wizard._show_step.assert_called_once_with()
        showinfo.assert_called_once()

    @patch("codex_sync_desktop.wizard.messagebox.showinfo")
    def test_missing_sessions_finishes_onboarding_and_shows_guidance(self, showinfo):
        app = SimpleNamespace(
            settings=SimpleNamespace(onboarding_complete=False),
            store=SimpleNamespace(save=Mock()),
            refresh_all=Mock(),
            show_page=Mock(),
        )
        wizard = SimpleNamespace(app=app, destroy=Mock())

        OnboardingWizard._initial_sync_failed(
            wizard,
            NoActiveSessionsError(Path("C:/Users/test/.codex/sessions")),
        )

        self.assertTrue(app.settings.onboarding_complete)
        app.store.save.assert_called_once_with(app.settings)
        wizard.destroy.assert_called_once_with()
        app.show_page.assert_called_once_with("sync")
        self.assertIn("C:\\Users\\test\\.codex\\sessions", showinfo.call_args.args[1])

    @patch("codex_sync_desktop.wizard.list_source_device_options", return_value=[("天文", "device")])
    @patch("codex_sync_desktop.wizard.VaultGit")
    def test_first_sync_with_remote_sessions_guides_direct_import(self, vault_git, _sources):
        vault_git.return_value.pull.return_value = SimpleNamespace(ok=True, output="pulled")
        with tempfile.TemporaryDirectory() as directory:
            app = SimpleNamespace(
                settings=SimpleNamespace(codex_path=Path(directory) / ".codex"),
                _report_progress=Mock(),
                _checked_git=Mock(),
                _export_and_push_work=Mock(),
            )
            wizard = SimpleNamespace(app=app)
            repository = SimpleNamespace(local_path=Path(directory) / "vault")

            summary = OnboardingWizard._initial_sync_work(wizard, repository, "")

        self.assertIn("天文", summary)
        self.assertIn("一键同步", summary)
        app._export_and_push_work.assert_not_called()
