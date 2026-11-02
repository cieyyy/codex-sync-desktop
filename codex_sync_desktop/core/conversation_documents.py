"""Export document files explicitly referenced by local conversation records."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from .config import default_codex_home, device_slug
from .documents import export_documents, SUPPORTED, LEGACY, _write
from .sessions import iter_export_session_files, open_session_text, export_sanitized_sessions

EXT = r'(?:markdown|docx|xlsx|docm|xlsm|doc|xls|md|txt|csv|tsv)'
ABSOLUTE = re.compile(r'(?:/(?:Users|home|tmp|private|var|mnt|Volumes|workspace|app|root|opt|data)/|[A-Za-z]:[\\/])[^\n\r\x00\"\'`<>|]{0,2048}?\.' + EXT + r'(?=$|[\s\"\'`<>):,;\]\\])', re.I)
QUOTED = re.compile(r'[\"\'`(<]([^\n\r\"\'`<>]{0,2048}?\.' + EXT + r')[\"\'`) >]', re.I)


def _strings(value):
    if isinstance(value, str):
        yield value
        if value.lstrip().startswith(('{', '[')):
            try:
                nested = json.loads(value)
            except ValueError:
                return
            if not isinstance(nested, str):
                yield from _strings(nested)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def export_conversation_documents(codex_home: Path, vault: Path, device: str, include_archived: bool = True) -> dict:
    codex_home = codex_home.expanduser().resolve()
    vault = vault.expanduser().resolve()
    references = {}
    missing = {}
    sessions_scanned = invalid_lines = 0
    for kind, session in iter_export_session_files(codex_home, include_archived):
        session_key = kind + '/' + session.relative_to(codex_home / kind).as_posix()
        sessions_scanned += 1
        cwd = None
        with open_session_text(session) as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    invalid_lines += 1
                    continue
                payload = record.get('payload') or {}
                if record.get('type') in ('session_meta', 'turn_context') and isinstance(payload, dict):
                    value = payload.get('cwd')
                    if isinstance(value, str) and Path(value).is_absolute():
                        cwd = Path(value).expanduser()
                for text in _strings(record):
                    if not re.search(r'\.' + EXT + r'\b', text, re.I):
                        continue
                    text = unquote(text.replace('file://', ''))
                    candidates = {match.group(0) for match in ABSOLUTE.finditer(text)}
                    candidates.update(match.group(1) for match in QUOTED.finditer(text))
                    if Path(text).suffix.lower() in SUPPORTED | LEGACY and '\n' not in text:
                        candidates.add(text)
                    for candidate in candidates:
                        candidate = candidate.strip().replace('\\ ', ' ')
                        if len(candidate) > 4096 or '://' in candidate or '\x00' in candidate:
                            continue
                        path = Path(candidate).expanduser()
                        if not path.is_absolute():
                            if cwd is None:
                                continue
                            path = cwd / path
                        if path.suffix.lower() not in SUPPORTED | LEGACY:
                            continue
                        try:
                            if path.is_symlink():
                                continue
                            path = path.resolve()
                            exists = path.is_file()
                        except OSError:
                            continue
                        if vault.resolve() == path or vault.resolve() in path.parents or codex_home.resolve() in path.parents:
                            continue
                        key = str(path)
                        if not exists:
                            missing.setdefault(key, set()).add(session_key)
                            continue
                        root = cwd.resolve() if cwd and (cwd.resolve() == path.parent or cwd.resolve() in path.parents) else path.parent
                        references.setdefault(key, {'root': root, 'sessions': set()})['sessions'].add(session_key)
    roots, selected, provenance = {}, {}, {}
    for name, reference in sorted(references.items()):
        root = reference['root']
        project = re.sub(r'[^A-Za-z0-9_-]', '-', root.name).strip('-') or 'project'
        project += '-' + hashlib.sha256(str(root).encode()).hexdigest()[:12]
        relative = Path(name).relative_to(root).as_posix()
        roots[project] = str(root)
        selected.setdefault(project, []).append(relative)
        provenance[project, relative] = {'source_path': name, 'sessions': sorted(reference['sessions'])}
    index = export_documents(vault, device, roots, selected_files=selected, write_index=False)
    for item in index['files']:
        item.update(provenance[item['project'], item['source']])
    index.update(mode='conversation-references', sessions_scanned=sessions_scanned,
                 invalid_session_lines=invalid_lines,
                 unresolved=[{'path': name, 'sessions': sorted(sessions)} for name, sessions in sorted(missing.items())])
    _write(vault / 'documents-text/devices' / device_slug(device) / 'index.json',
           (json.dumps(index, ensure_ascii=False, indent=2) + '\n').encode())
    return index


def main():
    parser = argparse.ArgumentParser(description='导出全部会话文字及会话明确引用的本机文档正文')
    parser.add_argument('--codex-home', type=Path, default=default_codex_home())
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--device', required=True)
    parser.add_argument('--save-settings', action='store_true', help='为桌面应用保存全部会话及引用文档同步设置')
    parser.add_argument('--documents-only', action='store_true')
    args = parser.parse_args()
    report = None if args.documents_only else export_sanitized_sessions(
        args.codex_home, args.vault, args.device, include_archived=True)
    index = export_conversation_documents(args.codex_home, args.vault, args.device)
    failures = sum(item['status'] != 'ok' for item in index['files'])
    summary = {'会话': report.sessions if report else index['sessions_scanned'],
               '文档成功': len(index['files']) - failures, '文档失败': failures,
               '无法定位的路径候选': len(index['unresolved']), '无效会话行': index['invalid_session_lines']}
    if args.save_settings:
        from .config import SettingsStore
        store = SettingsStore()
        settings = store.load()
        settings.include_archived_sessions = True
        settings.sync_referenced_documents = True
        settings.vault_path = str(args.vault.expanduser().resolve())
        settings.codex_home = str(args.codex_home.expanduser().resolve())
        settings.device_name = args.device
        store.save(settings)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures or index['invalid_session_lines']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
