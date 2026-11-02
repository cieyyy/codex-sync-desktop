import json
from pathlib import Path
import tempfile
from unittest import TestCase
from zipfile import ZipFile

from codex_sync_desktop.core.documents import export_documents, extract_text, W, S, R


class DocumentExportTests(TestCase):
    def test_word_preserves_paragraph_table_header_and_footnote_text(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'report.docx'
            with ZipFile(source, 'w') as archive:
                archive.writestr('word/document.xml', f'''<w:document xmlns:w="{W[1:-1]}"><w:body>
                <w:p><w:r><w:t>中文正文</w:t></w:r></w:p>
                <w:tbl><w:tr><w:tc><w:p><w:r><w:t>名称</w:t></w:r></w:p></w:tc>
                <w:tc><w:p><w:r><w:t>数值</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
                </w:body></w:document>''')
                archive.writestr('word/header1.xml', f'<w:hdr xmlns:w="{W[1:-1]}"><w:p><w:r><w:t>页眉</w:t></w:r></w:p></w:hdr>')
                archive.writestr('word/footnotes.xml', f'<w:footnotes xmlns:w="{W[1:-1]}"><w:footnote><w:p><w:r><w:t>脚注</w:t></w:r></w:p></w:footnote></w:footnotes>')
            text = extract_text(source)
            for expected in ['中文正文', '[表格]\n名称\t数值', '页眉', '脚注']:
                self.assertIn(expected, text)

    def test_excel_sparse_addresses_shared_strings_formulas_and_hidden_sheets(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'table.xlsx'
            with ZipFile(source, 'w') as archive:
                archive.writestr('xl/workbook.xml', f'<workbook xmlns="{S[1:-1]}" xmlns:r="{R[1:-1]}"><sheets><sheet name="预算" sheetId="1" state="hidden" r:id="rId1"/></sheets></workbook>')
                archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
                archive.writestr('xl/sharedStrings.xml', f'<sst xmlns="{S[1:-1]}"><si><r><t>项目</t></r><r><t>名称</t></r></si></sst>')
                archive.writestr('xl/worksheets/sheet1.xml', f'''<worksheet xmlns="{S[1:-1]}"><sheetData><row r="1">
                <c r="A1" t="s"><v>0</v></c><c r="C1"><f>SUM(A2:A3)</f><v>42</v></c>
                <c r="D1" t="inlineStr"><is><t>中文</t></is></c></row></sheetData><mergeCells><mergeCell ref="A2:B2"/></mergeCells></worksheet>''')
            text = extract_text(source)
            for expected in ['预算', 'hidden', 'A1\ts\t项目名称', 'C1\tn\t42', 'SUM(A2:A3)', 'D1\tinlineStr\t中文', 'A2:B2']:
                self.assertIn(expected, text)

    def test_export_is_incremental_excludes_symlinks_and_reports_unsupported_and_corrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            root.mkdir()
            vault = root / 'vault'
            vault.mkdir()
            (vault / 'private.md').write_text('do not export')
            (root / '.git').mkdir()
            (root / '.git' / 'hidden.md').write_text('do not export')
            (root / 'notes.md').write_bytes('中文\r\n正文'.encode())
            (root / 'broken.docx').write_bytes(b'not a zip')
            (root / 'old.xls').write_bytes(b'legacy')
            (root / 'link.md').symlink_to(root / 'notes.md')
            first = export_documents(vault, 'Laptop', {'demo': str(root)})
            self.assertEqual(len(first['files']), 3)
            good = next(item for item in first['files'] if item['status'] == 'ok')
            output = vault / good['text_path']
            self.assertEqual(output.read_text(), '中文\n正文')
            timestamp = output.stat().st_mtime_ns
            index_path = vault / 'documents-text/devices/laptop/index.json'
            index_timestamp = index_path.stat().st_mtime_ns
            self.assertEqual(first, export_documents(vault, 'Laptop', {'demo': str(root)}))
            self.assertEqual(timestamp, output.stat().st_mtime_ns)
            self.assertEqual(index_timestamp, index_path.stat().st_mtime_ns)
            (root / 'notes.md').unlink()
            index = export_documents(vault, 'Laptop', {'demo': str(root)})
            self.assertFalse(any(item['status'] == 'ok' for item in index['files']))
            self.assertTrue(output.exists())  # Historical copies are not deleted automatically.
            self.assertEqual(index, json.loads(index_path.read_text()))

    def test_path_validation_and_missing_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for roots in [{'../escape': str(root)}, {'demo': str(root / 'missing')}, {'demo': str(root / 'vault')}]:
                with self.assertRaises(ValueError):
                    export_documents(root / 'vault', 'Laptop', roots)

    def test_zip_expansion_limit_and_xml_entities_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'test.docx'
            with ZipFile(source, 'w') as archive:
                archive.writestr('word/document.xml', '<!DOCTYPE foo [<!ENTITY x "text">]><foo/>')
            with self.assertRaises(ValueError):
                extract_text(source)
