import io
from types import SimpleNamespace
import urllib.error
from unittest import TestCase
from unittest.mock import Mock, patch

from codex_sync_desktop.core.onboarding import check_github_connectivity, ConnectivityResult
from codex_sync_desktop.wizard import OnboardingWizard


class ConnectivityTests(TestCase):
    @patch('codex_sync_desktop.core.onboarding.urllib.request.build_opener')
    def test_api_quota_does_not_block_login_when_website_is_reachable(self, build_opener):
        limited = urllib.error.HTTPError('https://api.github.com/meta', 403, 'rate limit exceeded',
                                        {'X-RateLimit-Remaining': '0'}, io.BytesIO(b'{"message":"API rate limit exceeded"}'))
        website = Mock()
        website.__enter__ = Mock(return_value=SimpleNamespace(status=200))
        website.__exit__ = Mock(return_value=False)
        build_opener.return_value.open.side_effect = [limited, website]
        result = check_github_connectivity('http://127.0.0.1:7897')
        self.assertTrue(result.ok)
        self.assertTrue(result.api_limited)
        self.assertTrue(result.proxy_used)
        self.assertEqual(result.status, 403)
        request = build_opener.return_value.open.call_args_list[1].args[0]
        self.assertEqual(request.get_header('Accept'), 'text/html')
        self.assertEqual(request.get_method(), 'HEAD')

    @patch('codex_sync_desktop.core.onboarding.urllib.request.build_opener')
    def test_permission_denied_is_not_reported_as_rate_limit(self, build_opener):
        build_opener.return_value.open.side_effect = urllib.error.HTTPError(
            'https://api.github.com/meta', 403, 'Forbidden', {}, io.BytesIO(b'{"message":"Forbidden"}'))
        result = check_github_connectivity()
        self.assertFalse(result.ok)
        self.assertFalse(result.api_limited)
        self.assertEqual(result.status, 403)
        self.assertEqual(build_opener.return_value.open.call_count, 1)

    @patch('codex_sync_desktop.core.onboarding.urllib.request.build_opener')
    def test_rate_limit_alone_does_not_claim_website_is_reachable(self, build_opener):
        build_opener.return_value.open.side_effect = [
            urllib.error.HTTPError('https://api.github.com/meta', 429, 'Too Many Requests', {}, io.BytesIO(b'')),
            urllib.error.URLError('timed out'),
        ]
        result = check_github_connectivity()
        self.assertFalse(result.ok)
        self.assertTrue(result.api_limited)

    def test_unchecked_proxy_option_ignores_saved_address(self):
        wizard = SimpleNamespace(china_mode=SimpleNamespace(get=lambda: False),
                                 proxy_url=SimpleNamespace(get=lambda: 'http://127.0.0.1:7897'))
        self.assertEqual(OnboardingWizard._effective_proxy(wizard), '')
        wizard.china_mode = SimpleNamespace(get=lambda: True)
        self.assertEqual(OnboardingWizard._effective_proxy(wizard), 'http://127.0.0.1:7897')
        wizard.proxy_url = SimpleNamespace(get=lambda: '')
        with self.assertRaises(ValueError):
            OnboardingWizard._effective_proxy(wizard)

    def test_rate_limit_ui_reports_reachable_and_allows_next_step(self):
        settings = SimpleNamespace(proxy_url='', china_network_mode=True)
        wizard = SimpleNamespace(
            app=SimpleNamespace(settings=settings, store=SimpleNamespace(save=Mock())),
            china_mode=SimpleNamespace(get=lambda: False), _effective_proxy=lambda: '',
            network_status=Mock(), _update_next_state=Mock(),
        )
        OnboardingWizard._show_network_result(wizard, ConnectivityResult(True, 403, '接口额度已用尽。', False, True))
        self.assertTrue(wizard.network_ok)
        self.assertEqual(settings.proxy_url, '')
        self.assertIn('网络已连通', wizard.network_status.configure.call_args.kwargs['text'])
