from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase

from codex_sync_desktop.core.config import SettingsStore


class SettingsMigrationTests(TestCase):
    def test_existing_vault_from_pre_onboarding_version_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            app_home = Path(directory)
            (app_home / "config.json").write_text(
                json.dumps({"vault_path": str(app_home / "vault")}),
                encoding="utf-8",
            )

            settings = SettingsStore(app_home).load()

        self.assertTrue(settings.onboarding_complete)

    def test_explicit_incomplete_onboarding_remains_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            app_home = Path(directory)
            (app_home / "config.json").write_text(
                json.dumps({"vault_path": str(app_home / "vault"), "onboarding_complete": False}),
                encoding="utf-8",
            )

            settings = SettingsStore(app_home).load()

        self.assertFalse(settings.onboarding_complete)
