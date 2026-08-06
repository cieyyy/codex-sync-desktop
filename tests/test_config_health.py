import tempfile
import unittest
from pathlib import Path

from codex_sync_desktop.core.config_health import (
    effective_model_provider,
    inspect_model_provider_config,
    repair_model_provider_to_openai,
    resolve_session_model_provider,
)


class ModelProviderConfigTests(unittest.TestCase):
    def test_undefined_custom_provider_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "config.toml").write_text('model_provider = "custom"\n', encoding="utf-8")

            status = inspect_model_provider_config(home)

            self.assertFalse(status.valid)
            self.assertEqual(status.selected, "custom")
            self.assertIn("model_providers.custom", status.reason)
            self.assertEqual(effective_model_provider(home), "openai")

    def test_declared_custom_provider_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "config.toml").write_text(
                'model_provider = "custom"\n\n[model_providers.custom]\nname = "Custom"\nbase_url = "https://example.test"\n',
                encoding="utf-8",
            )

            self.assertTrue(inspect_model_provider_config(home).valid)

    def test_session_provider_resolution_preserves_builtins_and_configured_custom(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "config.toml").write_text(
                'model_provider = "openai"\n\n[model_providers.team_proxy]\nname = "Team Proxy"\nbase_url = "https://example.test"\n',
                encoding="utf-8",
            )

            for provider in ("openai", "ollama", "lmstudio", "amazon-bedrock"):
                self.assertEqual(resolve_session_model_provider(home, provider), provider)
            self.assertEqual(resolve_session_model_provider(home, "OpenAI"), "openai")
            self.assertEqual(resolve_session_model_provider(home, "team_proxy"), "team_proxy")
            self.assertEqual(resolve_session_model_provider(home, "missing_provider"), "openai")

    def test_repair_preserves_file_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / "config.toml"
            path.write_text(
                'model_provider = "custom" # selected\nmodel = "gpt-test"\n',
                encoding="utf-8",
            )

            backup = repair_model_provider_to_openai(home)

            self.assertTrue(backup.is_file())
            self.assertIn('model_provider = "custom"', backup.read_text(encoding="utf-8"))
            self.assertIn('model_provider = "openai" # selected', path.read_text(encoding="utf-8"))
            self.assertTrue(inspect_model_provider_config(home).valid)


if __name__ == "__main__":
    unittest.main()
