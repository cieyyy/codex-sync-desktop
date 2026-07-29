from __future__ import annotations

import queue
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from codex_sync_desktop.app import CodexSyncApp, dependency_setup_incomplete
from codex_sync_desktop.ui_theme import centered_geometry
from codex_sync_desktop.window_chrome import APP_USER_MODEL_ID, WindowChrome, bundled_asset_path, configure_windows_app_identity


class WindowPlacementTests(TestCase):
    def test_centers_dialog_over_parent(self):
        geometry = centered_geometry(860, 640, 100, 80, 1120, 760, 1920, 1080)

        self.assertEqual(geometry, "860x640+230+140")

    def test_clamps_dialog_to_visible_screen(self):
        geometry = centered_geometry(860, 640, 1700, 900, 1120, 760, 1920, 1080)

        self.assertEqual(geometry, "860x640+1044+424")


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
