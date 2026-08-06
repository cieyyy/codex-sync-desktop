import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from codex_sync_desktop.core.sessions import NoActiveSessionsError
from codex_sync_desktop.wizard import OnboardingWizard


class WizardWorkflowTests(TestCase):
    @patch("codex_sync_desktop.wizard.ttk.Checkbutton")
    def test_confirmation_uses_native_checkbox_indicator(self, checkbutton):
        parent = object()
        variable = object()
        control = checkbutton.return_value

        result = OnboardingWizard._checkmark(SimpleNamespace(), parent, "确认同步", variable)

        self.assertIs(result, control)
        checkbutton.assert_called_once_with(
            parent,
            text="确认同步",
            variable=variable,
            style="Checkmark.TCheckbutton",
            takefocus=True,
        )

    @patch("codex_sync_desktop.wizard.messagebox.showwarning")
    def test_unchecked_private_confirmation_blocks_next_step(self, showwarning):
        confirmation = Mock()
        confirmation.get.return_value = False
        wizard = SimpleNamespace(
            step=0,
            pages=[object(), object(), object(), object()],
            confirm_private=confirmation,
            _show_step=Mock(),
        )

        OnboardingWizard._next(wizard)

        confirmation.set.assert_not_called()
        self.assertEqual(wizard.step, 0)
        wizard._show_step.assert_not_called()
        showwarning.assert_called_once()

    def test_account_step_is_not_ready_until_all_requirements_pass(self):
        wizard = SimpleNamespace(step=2, account_status={"git": True, "gh": True, "authenticated": False})

        self.assertFalse(OnboardingWizard._step_ready(wizard))

        wizard.account_status["authenticated"] = True
        self.assertTrue(OnboardingWizard._step_ready(wizard))

    def test_repository_step_requires_all_configuration_fields(self):
        wizard = SimpleNamespace(
            step=3,
            network_ok=True,
            account_status={"git": True, "gh": True, "authenticated": True},
            repositories_loading=False,
            repository_mode=SimpleNamespace(get=lambda: "existing"),
            repository_reference=SimpleNamespace(get=lambda: ""),
            repository_name=SimpleNamespace(get=lambda: "unused"),
            local_path=SimpleNamespace(get=lambda: "C:/sync"),
            codex_home=SimpleNamespace(get=lambda: "C:/Users/test/.codex"),
            device_name=SimpleNamespace(get=lambda: "Office PC"),
        )

        self.assertFalse(OnboardingWizard._step_ready(wizard))

        wizard.repository_reference = SimpleNamespace(get=lambda: "owner/private-vault")
        self.assertTrue(OnboardingWizard._step_ready(wizard))

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
        expected_sessions_path = str(Path("C:/Users/test/.codex/sessions"))
        self.assertIn(expected_sessions_path, showinfo.call_args.args[1])

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
