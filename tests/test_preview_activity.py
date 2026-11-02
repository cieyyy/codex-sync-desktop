import json
from pathlib import Path
from unittest import TestCase
from codex_sync_desktop.core.import_preview import format_activity, preview_activity, sorted_activity_ids
from codex_sync_desktop.core.models import ImportItem


class PreviewActivityTests(TestCase):
    def test_display_in_beijing_and_use_numeric_sort_with_unknown_last(self):
        self.assertEqual(format_activity(0),'1970-01-01 08:00')
        values={'old':1,'unknown':None,'new':200,'also-old':1}
        self.assertEqual(sorted_activity_ids(values,values),['new','old','also-old','unknown'])
        self.assertEqual(sorted_activity_ids(values,values,descending=False),['old','also-old','new','unknown'])
        self.assertEqual(format_activity(None),'时间未知')

    def test_activity_comes_from_actual_content_not_upload(self):
        data='\n'.join(json.dumps({'timestamp':stamp}) for stamp in ['2020-01-01T00:00:00Z','2026-11-02T02:00:00Z']).encode()
        item=ImportItem('copy','file',Path('none'),Path('none'),incoming_content=data)
        self.assertEqual(format_activity(preview_activity(item)),'2026-11-02 10:00')
        self.assertIsNone(preview_activity(ImportItem('missing-source','file',Path('none'),Path('none'))))
