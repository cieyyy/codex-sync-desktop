from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from codex_sync_desktop.core import diagnostics


class PlatformDescriptionTests(TestCase):
    def test_windows_uses_version_api_without_shelling_out(self) -> None:
        version = SimpleNamespace(major=10, minor=0, build=22631)
        with (
            patch.object(diagnostics.sys, "platform", "win32"),
            patch.object(diagnostics.sys, "getwindowsversion", return_value=version, create=True),
            patch.object(diagnostics.platform, "platform", side_effect=AssertionError("must not run")),
        ):
            self.assertEqual(diagnostics.platform_description(), "Windows-10.0.22631")

    def test_platform_failure_falls_back_to_sys_platform(self) -> None:
        with (
            patch.object(diagnostics.sys, "platform", "test-platform"),
            patch.object(diagnostics.platform, "platform", side_effect=AttributeError("missing output")),
        ):
            self.assertEqual(diagnostics.platform_description(), "test-platform")
