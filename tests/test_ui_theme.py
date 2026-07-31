from __future__ import annotations

import queue
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from codex_sync_desktop.app import CodexSyncApp, dependency_setup_incomplete
from codex_sync_desktop.ui_theme import centered_geometry, vertical_scrollbar_required
from codex_sync_desktop.wizard import OnboardingWizard
from codex_sync_desktop.window_chrome import (
    APP_USER_MODEL_ID,
    GWL_EXSTYLE,
    GWLP_HWNDPARENT,
    GW_OWNER,
    TASKBAR_REFRESH_FLAGS,
    WS_EX_APPWINDOW,
    WS_EX_TOOLWINDOW,
    WindowChrome,
    bundled_asset_path,
    configure_windows_app_identity,
)


class WindowPlacementTests(TestCase):
    def test_centers_dialog_over_parent(self):
        geometry = centered_geometry(860, 640, 100, 80, 1120, 760, 1920, 1080)

        self.assertEqual(geometry, "860x640+230+140")

    def test_clamps_dialog_to_visible_screen(self):
        geometry = centered_geometry(860, 640, 1700, 900, 1120, 760, 1920, 1080)

        self.assertEqual(geometry, "860x640+1044+424")


class ScrollbarVisibilityTests(TestCase):
    def test_hides_scrollbar_when_content_fits(self):
        self.assertFalse(vertical_scrollbar_required(480, 480))
        self.assertFalse(vertical_scrollbar_required(479, 480))

    def test_shows_scrollbar_when_content_overflows(self):
        self.assertTrue(vertical_scrollbar_required(481, 480))

    def test_defers_visibility_until_viewport_is_measured(self):
        self.assertFalse(vertical_scrollbar_required(800, 1))

    def test_wizard_mounts_scrollbar_only_after_overflow(self):
        fake_wizard = SimpleNamespace(
            _page_scroll_update_pending=True,
            _page_scrollbar_visible=False,
            page_canvas=Mock(),
            page_scrollbar=Mock(),
            after_idle=Mock(),
            _schedule_page_scroll_update=Mock(),
        )
        fake_wizard.page_canvas.bbox.return_value = (0, 0, 800, 601)
        fake_wizard.page_canvas.winfo_height.return_value = 600

        OnboardingWizard._update_page_scrollregion(fake_wizard)

        self.assertTrue(fake_wizard._page_scrollbar_visible)
        fake_wizard.page_scrollbar.grid.assert_called_once_with(row=0, column=1, sticky="ns")
        fake_wizard.page_scrollbar.grid_remove.assert_not_called()

    def test_wizard_removes_scrollbar_when_content_fits(self):
        fake_wizard = SimpleNamespace(
            _page_scroll_update_pending=True,
            _page_scrollbar_visible=True,
            page_canvas=Mock(),
            page_scrollbar=Mock(),
            after_idle=Mock(),
            _schedule_page_scroll_update=Mock(),
        )
        fake_wizard.page_canvas.bbox.return_value = (0, 0, 800, 600)
        fake_wizard.page_canvas.winfo_height.return_value = 600

        OnboardingWizard._update_page_scrollregion(fake_wizard)

        self.assertFalse(fake_wizard._page_scrollbar_visible)
        fake_wizard.page_scrollbar.grid_remove.assert_called_once_with()
        fake_wizard.page_canvas.yview_moveto.assert_called_once_with(0.0)


class TaskFeedbackTests(TestCase):
    def test_progress_message_is_queued_from_worker(self):
        fake_app = SimpleNamespace(messages=queue.Queue())

        CodexSyncApp._report_progress(fake_app, "正在推送到 GitHub")

        self.assertEqual(fake_app.messages.get_nowait(), ("progress", "正在推送到 GitHub"))

    def test_missing_git_or_github_cli_requires_tool_setup(self):
        self.assertTrue(dependency_setup_incomplete({"git": False, "gh": True}))
        self.assertTrue(dependency_setup_incomplete({"git": True, "gh": False}))
        self.assertFalse(dependency_setup_incomplete({"git": True, "gh": True}))

    def test_mouse_navigation_releases_dotted_focus_ring(self):
        focus_set = Mock()
        fake_app = SimpleNamespace(after_idle=Mock(), chrome=SimpleNamespace(body=SimpleNamespace(focus_set=focus_set)))

        CodexSyncApp._release_nav_mouse_focus(fake_app, None)

        fake_app.after_idle.assert_called_once_with(focus_set)

    def test_long_status_text_uses_scrollable_entry_and_resets_to_start(self):
        fake_app = SimpleNamespace(
            busy_text=Mock(),
            busy_label=Mock(),
            after_idle=Mock(),
            _reset_status_scroll=Mock(),
        )
        text = "正在分析来源设备 desktop-0789039 的全部会话"

        CodexSyncApp._set_status_text(fake_app, text)

        fake_app.busy_text.set.assert_called_once_with(text)
        fake_app.busy_label.configure.assert_called_once_with(style="Status.TEntry")
        fake_app.after_idle.assert_called_once_with(fake_app._reset_status_scroll)

    def test_status_scroll_returns_to_leading_text(self):
        fake_app = SimpleNamespace(busy_label=Mock())

        CodexSyncApp._reset_status_scroll(fake_app)

        fake_app.busy_label.xview_moveto.assert_called_once_with(0.0)


class WindowsChromeTests(TestCase):
    @patch("codex_sync_desktop.window_chrome.os.name", "posix")
    def test_non_windows_identity_is_skipped(self):
        self.assertFalse(configure_windows_app_identity())

    @patch("codex_sync_desktop.window_chrome.os.name", "nt")
    @patch("codex_sync_desktop.window_chrome.ctypes.windll", create=True)
    def test_windows_identity_uses_stable_app_id(self, mocked_windll):
        mocked_windll.shell32.SetCurrentProcessExplicitAppUserModelID.return_value = 0

        self.assertTrue(configure_windows_app_identity())
        mocked_windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(APP_USER_MODEL_ID)

    @patch("codex_sync_desktop.window_chrome.ctypes.windll", create=True)
    def test_native_window_handle_uses_64_bit_safe_parent(self, mocked_windll):
        mocked_windll.user32.GetParent.return_value = 456
        chrome = SimpleNamespace(window=SimpleNamespace(winfo_id=lambda: 123))

        self.assertEqual(WindowChrome._native_window_handle(chrome), 456)
        mocked_windll.user32.GetParent.assert_called_once_with(123)

    def test_bundled_asset_path_uses_pyinstaller_root(self):
        with patch("codex_sync_desktop.window_chrome.sys._MEIPASS", "C:/bundle", create=True):
            self.assertEqual(bundled_asset_path("icon.ico"), Path("C:/bundle/assets/icon.ico"))

    @patch("codex_sync_desktop.window_chrome.ctypes.windll", create=True)
    def test_taskbar_repair_clears_tool_window_owner_and_refreshes_frame(self, mocked_windll):
        user32 = mocked_windll.user32
        user32.GetWindowLongPtrW.return_value = WS_EX_TOOLWINDOW
        user32.SetWindowPos.return_value = 1
        user32.GetWindow.return_value = 0
        chrome = SimpleNamespace(
            title="Codex Sync Desktop  0.7.1",
            _native_window_handle=Mock(return_value=456),
            _set_native_icon=Mock(return_value=True),
        )
        chrome.is_taskbar_registered = Mock(return_value=True)

        result = WindowChrome._repair_taskbar_window(chrome)

        self.assertTrue(result)
        user32.SetWindowLongPtrW.assert_any_call(456, GWL_EXSTYLE, WS_EX_APPWINDOW)
        user32.SetWindowLongPtrW.assert_any_call(456, GWLP_HWNDPARENT, 0)
        user32.SetWindowTextW.assert_called_once_with(456, "Codex Sync Desktop  0.7.1")
        user32.SetWindowPos.assert_called_once_with(456, 0, 0, 0, 0, 0, TASKBAR_REFRESH_FLAGS)
        chrome._set_native_icon.assert_called_once_with(456)

    @patch("codex_sync_desktop.window_chrome.ctypes.windll", create=True)
    def test_taskbar_registration_requires_appwindow_without_owner(self, mocked_windll):
        user32 = mocked_windll.user32
        user32.GetWindowLongPtrW.return_value = WS_EX_APPWINDOW
        user32.GetWindow.return_value = 0
        chrome = SimpleNamespace(enabled=True, _native_window_handle=Mock(return_value=456))

        self.assertTrue(WindowChrome.is_taskbar_registered(chrome))
        user32.GetWindow.assert_called_once_with(456, GW_OWNER)

    @patch("codex_sync_desktop.window_chrome.ctypes.windll", create=True)
    def test_taskbar_registration_rejects_tool_window_or_owner(self, mocked_windll):
        user32 = mocked_windll.user32
        chrome = SimpleNamespace(enabled=True, _native_window_handle=Mock(return_value=456))

        user32.GetWindowLongPtrW.return_value = WS_EX_APPWINDOW | WS_EX_TOOLWINDOW
        user32.GetWindow.return_value = 0
        self.assertFalse(WindowChrome.is_taskbar_registered(chrome))

        user32.GetWindowLongPtrW.return_value = WS_EX_APPWINDOW
        user32.GetWindow.return_value = 999
        self.assertFalse(WindowChrome.is_taskbar_registered(chrome))
