from unittest import TestCase
from unittest.mock import Mock, patch

from codex_sync_desktop.app import configure_cli_output_encoding


class CliOutputTests(TestCase):
    def test_diagnostics_output_reconfigures_supported_stream_to_utf8(self):
        stream = Mock()

        with patch("codex_sync_desktop.app.sys.stdout", stream):
            configure_cli_output_encoding()

        stream.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")

    def test_diagnostics_output_accepts_stream_without_reconfigure(self):
        stream = object()

        with patch("codex_sync_desktop.app.sys.stdout", stream):
            configure_cli_output_encoding()
