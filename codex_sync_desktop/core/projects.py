"""Portable project provenance. This module never changes Codex project assignments."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .backups import find_state_databases

MEMBERSHIP_FILE = 'sync-project-membership.json'


def _group(project_id, name, roots=(), *, kind='local', status='confirmed', origin='codex'):
    return {'group_id': f'{kind}:{project_id}', 'project_id': str(project_id),
            'name': str(name), 'roots': list(roots), 'kind': kind, 'status': status, 'origin': origin}


def _special(status):
    return {'group_id': status, 'name': {'unassigned': '未归属项目', 'unknown': '项目未知'}[status],
            'status': status, 'origin': 'codex' if status == 'unassigned' else 'unknown', 'roots': []}


def read_project_context(home: Path):
    state_path = home / '.codex-global-state.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    definitions = {}
    aliases = state.get('app-server-project-id-by-legacy-project-id-by-host', {}).get('local:' + str(home), {})
    for identity, project in state.get('local-projects', {}).items():
        key = str(aliases.get(identity, identity))
        definitions[key] = _group(key, project.get('name') or key, project.get('rootPaths') or (), origin='codex_state')
    assignments = {}
    for identity, assignment in state.get('thread-project-assignments', {}).items():
        project_id = str(assignment.get('projectId') or '')
        if project_id:
            project_id = str(aliases.get(project_id, project_id))
            assignments[identity] = definitions.get(project_id) or _group(project_id, '项目 ' + project_id,
                kind=assignment.get('projectKind') or 'local', origin='codex_state')
    # The newest threads database is the authority for native project membership.
    for database in sorted(find_state_databases(home), key=lambda p: p.stat().st_mtime):
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'projects' in tables:
                for identity, name in connection.execute('SELECT id, name FROM projects'):
                    roots = [row[0] for row in connection.execute('SELECT path FROM project_roots WHERE project_id=? ORDER BY position', (identity,))] if 'project_roots' in tables else []
                    definitions[str(identity)] = _group(identity, name or identity, roots, origin='codex_database')
            if 'threads' in tables:
                columns = {row[1] for row in connection.execute('PRAGMA table_info(threads)')}
                if 'project_id' in columns:
                    for identity, project_id in connection.execute("SELECT id, project_id FROM threads WHERE project_id IS NOT NULL AND project_id != ?", ("",)):
                        assignments[str(identity)] = definitions.get(str(project_id)) or _group(project_id, '项目 ' + str(project_id), origin='codex_database')
    # Resolve state aliases to the richer database definition, including current names.
    assignments = {identity: definitions.get(value.get('project_id'), value) for identity, value in assignments.items()}
    saved_path = home / MEMBERSHIP_FILE
    saved = json.loads(saved_path.read_text(encoding='utf-8')).get('sessions', {}) if saved_path.exists() else {}
    return {'projects': definitions, 'assignments': assignments,
            'projectless': set(state.get('projectless-thread-ids', [])), 'saved': saved}


def _normal(path):
    value = str(path).replace('\\', '/').rstrip('/')
    return value.casefold() if len(value) > 1 and value[1] == ':' else value


def infer_project(cwd: str, definitions=()):
    if not cwd:
        return _special('unknown')
    normalized = _normal(cwd)
    matching = [(len(_normal(root)), project) for project in definitions for root in project.get('roots', [])
                if normalized == _normal(root) or normalized.startswith(_normal(root) + '/')]
    if matching:
        return dict(max(matching, key=lambda pair: pair[0])[1], status='inferred', origin='workspace_path')
    identity = hashlib.sha256(normalized.encode()).hexdigest()[:20]
    return _group(identity, normalized.rsplit('/', 1)[-1] or cwd, [cwd], kind='cwd', status='inferred', origin='cwd')


def session_project(context, identity: str, cwd: str):
    if identity in context['assignments']:
        return dict(context['assignments'][identity])
    if identity in context['projectless']:
        return _special('unassigned')
    if identity in context['saved']:
        return normalize_project(context['saved'][identity])
    return infer_project(cwd, context['projects'].values())


def normalize_project(value):
    if not isinstance(value, dict) or not value.get('group_id') or not value.get('name'):
        return _special('unknown')
    result = {key: str(value[key]) for key in ('group_id', 'project_id', 'name', 'kind', 'status', 'origin') if key in value}
    result['roots'] = [str(root) for root in value.get('roots', []) if isinstance(root, str)]
    if isinstance(value.get('candidates'), list):
        result['candidates'] = [normalize_project(candidate) for candidate in value['candidates']]
    return result


def combine_projects(values, cwd=''):
    choices = [normalize_project(value) for value in values if isinstance(value, dict)]
    # Confirmed native records are stronger evidence than directory inference.
    confirmed = [value for value in choices if value.get('status') in ('confirmed', 'unassigned', 'conflict')]
    choices = confirmed or [value for value in choices if value.get('status') != 'unknown']
    unique = {value['group_id']: value for value in choices}
    if len(unique) == 1:
        return next(iter(unique.values()))
    if len(unique) > 1:
        return {'group_id': 'conflict:' + hashlib.sha256('|'.join(sorted(unique)).encode()).hexdigest()[:20],
                'name': '项目归属冲突', 'status': 'conflict', 'origin': 'multiple_sources',
                'roots': [], 'candidates': list(unique.values())}
    return infer_project(cwd)


def project_label(project):
    project = normalize_project(project)
    return project['name'] + ('（目录推断）' if project.get('status') == 'inferred' else '')


def project_detail(project):
    project = normalize_project(project)
    text = project_label(project)
    if project.get('roots'):
        text += ' · ' + '；'.join(project['roots'])
    if project.get('candidates'):
        text += '：' + '；'.join(project_detail(value) for value in project['candidates'])
    return text


def save_imported_projects(home: Path, items):
    path = home / MEMBERSHIP_FILE
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'format': 1, 'sessions': {}}
    changed = False
    for item in items:
        if item.task_id not in data['sessions']:
            data['sessions'][item.task_id] = normalize_project(item.project)
            changed = True
    if changed:
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temp.replace(path)


def session_cwd(path: Path):
    from .sessions import open_session_text
    if not path.is_file():
        return ''
    with open_session_text(path) as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get('type') == 'session_meta':
                return str((row.get('payload') or {}).get('cwd') or '')
    return ''
