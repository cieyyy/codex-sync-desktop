"""Verify document extraction through a built macOS executable, using fictional data."""
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import zstandard

app = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
project = root / 'project with spaces'
project.mkdir(parents=True, exist_ok=True)
home = root / 'codex'
vault = root / 'vault'
(home / 'sessions').mkdir(parents=True, exist_ok=True)
(home / 'archived_sessions').mkdir(parents=True, exist_ok=True)
(project / 'notes.md').write_text('# 模拟文档\n打包后的中文正文', encoding='utf-8')
with ZipFile(project / 'report.docx', 'w') as archive:
    archive.writestr('word/document.xml', '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
    <w:p><w:r><w:t>模拟 Word 正文</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>名称</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>数值</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>''')
with ZipFile(project / 'budget.xlsx', 'w') as archive:
    archive.writestr('xl/workbook.xml', '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="预算" sheetId="1" r:id="rId1"/></sheets></workbook>''')
    archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
    archive.writestr('xl/worksheets/sheet1.xml', '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>21</v></c><c r="B1"><f>A1*2</f><v>42</v></c></row></sheetData></worksheet>''')
rows = [
    {'type': 'session_meta', 'payload': {'id': 'package-test', 'cwd': str(project)}},
    {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': '\n'.join(str(project / name) for name in ('notes.md', 'report.docx', 'budget.xlsx'))}},
]
text = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
(home / 'sessions/test.jsonl').write_text(text, encoding='utf-8')
(home / 'archived_sessions/old.jsonl.zst').write_bytes(zstandard.ZstdCompressor().compress(text.encode()))
executable = app / 'Contents/MacOS/Codex Sync Desktop'
result = subprocess.run([str(executable), '--export-documents', '--codex-home', str(home), '--vault', str(vault)],
                        capture_output=True, text=True, check=True, timeout=60)
summary = json.loads(result.stdout)
assert summary == {'sessions': 2, 'documents': 3, 'failed': 0, 'unresolved': 0}, summary
indexes = list((vault / 'documents-text/devices').glob('*/index.json'))
assert len(indexes) == 1
index = json.loads(indexes[0].read_text())
checks = {'notes.md': '打包后的中文正文', 'report.docx': '名称\t数值', 'budget.xlsx': 'A1*2'}
for entry in index['files']:
    content = (vault / entry['text_path']).read_text()
    assert checks[entry['source']] in content
    assert len(entry['sessions']) == 2
(root / 'verification.json').write_text(json.dumps({'status': 'passed', **summary}, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'status': 'passed', **summary}, ensure_ascii=False))
