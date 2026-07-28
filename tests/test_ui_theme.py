from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest import TestCase

from codex_sync_desktop.app import CodexSyncApp, dependency_setup_incomplete
from codex_sync_desktop.ui_theme import centered_geometry


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
