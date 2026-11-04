"""Resolve a single proxy policy for Git, gh and Python HTTP downloads."""
from __future__ import annotations

import os
import sys
import urllib.request
from typing import Mapping


def system_proxies(platform_name: str | None = None) -> dict[str, str]:
    platform_name = platform_name or sys.platform
    getter_name = ('getproxies_macosx_sysconf' if platform_name == 'darwin' else
                   'getproxies_registry' if platform_name == 'win32' else '')
    getter = getattr(urllib.request, getter_name, None) if getter_name else None
    try:
        values = getter() if getter else {}
    except (OSError, ValueError):
        values = {}
    return {key: str(value) for key, value in values.items() if key in ('http', 'https', 'no') and value}


def resolve_proxies(manual: str = '', environ: Mapping[str, str] | None = None,
                    platform_name: str | None = None) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    proxies = system_proxies(platform_name)
    # Explicit environment overrides system settings, matching CLI expectations.
    for key in ('http', 'https', 'all', 'no'):
        name = 'no_proxy' if key == 'no' else key + '_proxy'
        value = env.get(name, env.get(name.upper(), ''))
        if value:
            proxies[key] = value
    if manual:
        proxies.update(http=manual, https=manual)
        proxies.pop('all', None)
    return proxies


def proxy_environment(env: Mapping[str, str], manual: str = '', platform_name: str | None = None) -> dict[str, str]:
    result = dict(env)
    for key, value in resolve_proxies(manual, env, platform_name).items():
        variable = 'no_proxy' if key == 'no' else key + '_proxy'
        result[variable] = result[variable.upper()] = value
    return result
