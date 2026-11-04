from unittest import TestCase
from unittest.mock import patch
from codex_sync_desktop.core.proxy import proxy_environment, resolve_proxies, system_proxies
from codex_sync_desktop.core.onboarding import _url_handlers
from codex_sync_desktop.core.git_client import command_environment


class ProxyPolicyTests(TestCase):
    @patch('codex_sync_desktop.core.proxy.system_proxies', return_value={'http':'http://127.0.0.1:7897', 'https':'http://127.0.0.1:7897'})
    def test_system_proxy_is_used_by_git_and_gh(self, _system):
        env = command_environment({'PATH':'/usr/bin'}, platform_name='darwin')
        self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:7897')
        self.assertEqual(env['http_proxy'], env['HTTP_PROXY'])

    @patch('codex_sync_desktop.core.proxy.system_proxies', return_value={'https':'http://system:7897'})
    def test_python_downloads_follow_same_system_proxy(self, _system):
        with patch.dict('os.environ', {}, clear=True):
            handler = _url_handlers('')[0]
        self.assertEqual(handler.proxies['https'], 'http://system:7897')

    @patch('codex_sync_desktop.core.proxy.system_proxies', return_value={'https':'http://system:7897'})
    def test_manual_overrides_environment_and_system(self, _system):
        env = proxy_environment({'https_proxy':'http://environment:7890'}, 'http://manual:1234')
        self.assertEqual(env['https_proxy'], 'http://manual:1234')
        self.assertEqual(env['HTTPS_PROXY'], 'http://manual:1234')

    @patch('codex_sync_desktop.core.proxy.system_proxies', return_value={})
    def test_no_proxy_does_not_invent_a_listening_port(self, _system):
        self.assertEqual(resolve_proxies(environ={}), {})

    @patch('codex_sync_desktop.core.proxy.system_proxies', return_value={'http':'http://http:80','https':'http://https:81'})
    def test_scheme_specific_proxy_and_bypass_preserved(self, _system):
        env = proxy_environment({'NO_PROXY':'localhost,127.0.0.1'})
        self.assertEqual(env['HTTP_PROXY'], 'http://http:80')
        self.assertEqual(env['HTTPS_PROXY'], 'http://https:81')
        self.assertEqual(env['no_proxy'], 'localhost,127.0.0.1')

    @patch('codex_sync_desktop.core.proxy.urllib.request.getproxies_macosx_sysconf', create=True)
    def test_native_macos_reader_refreshes_on_each_request(self, reader):
        reader.side_effect = [{'https':'http://127.0.0.1:7897'},{}]
        self.assertTrue(system_proxies('darwin'))
        self.assertEqual(system_proxies('darwin'), {})
