"""Small, dependency-free text exports for explicitly selected project documents."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from .config import device_slug

SUPPORTED = {'.md', '.markdown', '.txt', '.csv', '.tsv', '.docx', '.xlsx'}
LEGACY = {'.doc', '.xls', '.xlsm', '.docm'}
EXCLUDED = {'.git', '.codex', '.venv', 'venv', 'node_modules', '__pycache__',
            'sessions-text', 'documents-text'}
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def _xml(archive: ZipFile, member: str) -> ET.Element:
    info = archive.getinfo(member)
    if info.file_size > MAX_XML_BYTES:
        raise ValueError('文档内部 XML 超过大小限制')
    data = archive.read(member)
    if b'<!DOCTYPE' in data or b'<!ENTITY' in data:
        raise ValueError('不支持含实体声明的 XML')
    return ET.fromstring(data)


def _word_text(element: ET.Element) -> str:
    parts = []
    for node in element.iter():
        if node.tag == W + 'p' and parts and parts[-1] != '\n':
            parts.append('\n')
        elif node.tag == W + 't':
            parts.append(node.text or '')
        elif node.tag == W + 'tab':
            parts.append('\t')
        elif node.tag in (W + 'br', W + 'cr'):
            parts.append('\n')
    return ''.join(parts)


def _docx(archive: ZipFile) -> str:
    lines = []
    # Include headers, footers, footnotes and endnotes, but no embedded media.
    members = ['word/document.xml'] + sorted(
        name for name in archive.namelist()
        if re.fullmatch(r'word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml', name)
    )
    for member in members:
        root = _xml(archive, member)
        lines.append('## ' + member)
        body = root.find(W + 'body') if member == 'word/document.xml' else root
        if body is None:
            raise ValueError('Word 文档缺少正文')
        for node in body:
            if node.tag == W + 'tbl':
                table = io.StringIO()
                writer = csv.writer(table, delimiter='\t', lineterminator='\n')
                for row in node.findall(W + 'tr'):
                    writer.writerow([_word_text(cell) for cell in row.findall(W + 'tc')])
                lines.append('[表格]\n' + table.getvalue().rstrip('\n'))
            else:
                text = _word_text(node)
                if text:
                    lines.append(text)
    return '\n'.join(lines) + '\n'


def _xlsx(archive: ZipFile) -> str:
    strings = []
    if 'xl/sharedStrings.xml' in archive.namelist():
        strings = [''.join(t.text or '' for t in node.iter(S + 't'))
                   for node in _xml(archive, 'xl/sharedStrings.xml').findall(S + 'si')]
    relations = {node.attrib['Id']: node.attrib.get('Target', '')
                 for node in _xml(archive, 'xl/_rels/workbook.xml.rels')
                 if node.attrib.get('TargetMode') != 'External'}
    out = io.StringIO()
    writer = csv.writer(out, delimiter='\t', lineterminator='\n')
    for sheet in _xml(archive, 'xl/workbook.xml').iter(S + 'sheet'):
        target = relations.get(sheet.attrib.get(R + 'id'), '')
        path = PurePosixPath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
        if '..' in path.parts or not str(path).startswith('xl/'):
            raise ValueError('无效工作表路径')
        writer.writerow(['工作表', sheet.attrib.get('name', ''), '状态', sheet.attrib.get('state', 'visible')])
        writer.writerow(['单元格', '类型', '值（日期可能为 Excel 序列值）', '公式', '样式编号'])
        worksheet = _xml(archive, str(path))
        for cell in worksheet.iter(S + 'c'):
            kind = cell.attrib.get('t', 'n')
            value = cell.findtext(S + 'v', '')
            if kind == 's':
                value = strings[int(value)]
            elif kind == 'inlineStr':
                value = ''.join(t.text or '' for t in cell.iter(S + 't'))
            formula = cell.find(S + 'f')
            # Shared/array formula attributes retain their anchor references.
            expression = '' if formula is None else json.dumps(
                {'text': formula.text or '', 'attributes': formula.attrib}, ensure_ascii=False)
            writer.writerow([cell.attrib.get('r', ''), kind, value, expression, cell.attrib.get('s', '')])
        for merged in worksheet.iter(S + 'mergeCell'):
            writer.writerow(['合并区域', merged.attrib.get('ref', '')])
    return out.getvalue()


def extract_text(source: Path) -> str:
    if source.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('源文件超过 32 MiB，未导出')
    suffix = source.suffix.lower()
    if suffix in {'.docx', '.xlsx'}:
        with ZipFile(source) as archive:
            if len(archive.infolist()) > 10000 or sum(i.file_size for i in archive.infolist()) > MAX_XML_BYTES:
                raise ValueError('文档解压大小或条目数超过限制')
            text = _docx(archive) if suffix == '.docx' else _xlsx(archive)
    else:
        text = source.read_text(encoding='utf-8-sig')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if len(text.encode('utf-8')) > MAX_OUTPUT_BYTES:
        raise ValueError('提取文字超过 32 MiB，未导出')
    return text


def _write(path: Path, data: bytes) -> None:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('导出路径不能经过符号链接')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return
    temp = path.with_name(path.name + '.tmp')
    if temp.is_symlink():
        raise ValueError('临时路径不能是符号链接')
    temp.write_bytes(data)
    temp.replace(path)


def export_documents(vault: Path, device: str, roots: dict[str, str], selected_files: dict[str, list[str]] | None = None, write_index: bool = True) -> dict:
    """Only files listed as ok in this index are current, readable exports."""
    vault = vault.expanduser().resolve()
    output = vault / 'documents-text' / 'devices' / device_slug(device)
    entries = []
    for project, directory in sorted(roots.items()):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', project):
            raise ValueError('项目标识只能包含英文字母、数字、下划线和短横线')
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f'文档目录不存在：{directory}')
        if root == vault or vault in root.parents:
            raise ValueError('不能将同步仓库作为文档源')
        if selected_files is not None:
            chosen = selected_files.get(project, [])
            if any(Path(name).is_absolute() or '..' in Path(name).parts for name in chosen):
                raise ValueError('所选文档路径必须位于项目目录内')
            walk = [(str(root), [], chosen)]
        else:
            walk = os.walk(root, followlinks=False)
        for current, dirs, files in walk:
            base = Path(current)
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not d.startswith('.')
                             and not (base / d).is_symlink() and (base / d).resolve() != vault)
            for name in sorted(files):
                source = base / name
                if source.is_symlink() or name.startswith('.') or source.suffix.lower() not in SUPPORTED | LEGACY:
                    continue
                relative = source.relative_to(root).as_posix()
                entry = {'project': project, 'source': relative, 'status': 'error'}
                try:
                    if source.suffix.lower() in LEGACY:
                        raise ValueError('请先另存为 .docx 或 .xlsx；旧格式或含宏文件未提取')
                    before = source.read_bytes() if source.stat().st_size <= MAX_SOURCE_BYTES else b''
                    digest = hashlib.sha256(before).hexdigest()
                    text = extract_text(source)
                    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                        raise ValueError('读取期间文件发生变化，请重试')
                    data = text.encode('utf-8')
                    destination = output / project / (relative + '.txt')
                    _write(destination, data)
                    entry.update(status='ok', text_path=destination.relative_to(vault).as_posix(),
                                 source_sha256=digest, text_sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
                except (OSError, ValueError, KeyError, IndexError, ET.ParseError, EOFError) as exc:
                    entry['error'] = str(exc)
                except Exception as exc:
                    # A corrupt Office archive must not prevent other files from exporting.
                    entry['error'] = f'{type(exc).__name__}: {exc}'
                entries.append(entry)
    index = {'format': 1, 'device': device, 'projects': sorted(roots), 'files': entries}
    if write_index:
        _write(output / 'index.json', (json.dumps(index, ensure_ascii=False, indent=2) + '\n').encode())
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description='仅同步明确指定的项目文档文字，不上传原件')
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--device', required=True)
    parser.add_argument('--save-projects', action='store_true', help='保存文档目录至桌面应用设置，后续随会话导出')
    parser.add_argument('--project', action='append', required=True, metavar='NAME=PATH')
    args = parser.parse_args()
    roots = {}
    for value in args.project:
        name, sep, path = value.partition('=')
        if not sep or not path or name in roots:
            parser.error('--project 需要不重复的 NAME=PATH')
        roots[name] = path
    index = export_documents(args.vault, args.device, roots)
    if args.save_projects:
        from .config import SettingsStore
        store = SettingsStore()
        settings = store.load()
        settings.document_roots = {name: str(Path(path).expanduser().resolve()) for name, path in roots.items()}
        store.save(settings)
    failures = [item for item in index['files'] if item['status'] != 'ok']
    print(json.dumps({'导出': len(index['files']) - len(failures), '失败': failures}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
