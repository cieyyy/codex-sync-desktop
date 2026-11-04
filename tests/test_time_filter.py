import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import TestCase

from codex_sync_desktop.core.config import Settings, SettingsStore
from codex_sync_desktop.core.import_preview import apply_title_overrides
from codex_sync_desktop.core.sessions import apply_import, export_sanitized_sessions, plan_all_import
from codex_sync_desktop.core.time_filter import last_activity, resolve_time_range
from tests.helpers import write_session


class TimeFilterTests(TestCase):
    def test_presets_include_today_and_custom_end_is_inclusive(self):
        tz = timezone(timedelta(hours=9))
        now = datetime(2026, 11, 2, 12, tzinfo=tz)
        since, before = resolve_time_range('最近7天', now=now)
        self.assertEqual(datetime.fromtimestamp(since, tz).isoformat(), '2026-10-27T00:00:00+09:00')
        self.assertEqual(datetime.fromtimestamp(before, tz).isoformat(), '2026-11-03T00:00:00+09:00')
        self.assertEqual(resolve_time_range('自定义日期', '2026-10-27', '2026-11-02', now=now), (since, before))
        self.assertIsNone(resolve_time_range('自定义日期', '', '2026-11-02', now=now)[0])
        self.assertIsNone(resolve_time_range('自定义日期', '2026-11-02', '', now=now)[1])

    def test_invalid_ranges_fail_before_import(self):
        for args in [('未知', '', ''), ('自定义日期', '', ''), ('自定义日期', '2026-02-30', ''),
                     ('自定义日期', '2026-11-02', '2026-10-01'), ('自定义日期', '2026-1-2', '')]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                resolve_time_range(*args)

    def test_range_saved_and_old_settings_default_to_all(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory))
            self.assertEqual(store.load().sync_time_mode, '全部时间')
            store.save(Settings(sync_time_mode='自定义日期', sync_start_date='2026-10-01', sync_end_date='2026-11-02'))
            self.assertEqual(store.load().sync_end_date, '2026-11-02')

    def test_uses_latest_activity_across_copies_not_upload_or_file_date(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault, home = root / 'vault', root / 'target'
            for device, date in [('old-device', '2020-01-01'), ('new-device', '2026-11-02')]:
                source = root / device
                path = write_session(source, 'recent-active')
                path.write_text(path.read_text().replace('2026-07-25', date))
                export_sanitized_sessions(source, vault, device)
            old = root / 'old-only'
            path = write_session(old, 'old-only')
            path.write_text(path.read_text().replace('2026-07-25', '2020-01-01'))
            export_sanitized_sessions(old, vault, 'old-only')
            since, before = resolve_time_range('自定义日期', '2026-11-01', '2026-11-02')
            plan = plan_all_import(home, vault, activity_since=since, activity_before=before)
            self.assertEqual(plan.counts, {'skipped-time': 1, 'copy': 1})
            self.assertEqual(apply_title_overrides(plan, {'old-only': '不能应用此标题'}), 0)
            self.assertNotIn('old-only', plan.title_updates)
            result = apply_import(plan)
            self.assertEqual(len(result['copied']), 1)
            self.assertRegex(result['copied'][0].name, r'^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-recent-active\.jsonl$')
            # Filtering does not remove the old conversation from the repository.
            self.assertTrue(path.exists())
            self.assertEqual(plan_all_import(home, vault).counts, {'copy': 1, 'skipped-existing': 1})

    def test_undated_records_skipped_only_when_filter_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_session(root / 'source', 'undated')
            records = [json.loads(line) for line in path.read_text().splitlines()]
            for item in records:
                item.pop('timestamp', None)
                item['payload'].pop('timestamp', None)
            path.write_text(''.join(json.dumps(item)+'\n' for item in records))
            export_sanitized_sessions(root/'source', root/'vault', 'source')
            self.assertEqual(plan_all_import(root/'target', root/'vault', activity_since=0).counts, {'skipped-time': 1})
            self.assertEqual(plan_all_import(root/'target', root/'vault').counts, {'copy': 1})

    def test_timezone_and_boundary_activity(self):
        records = [{'timestamp': '2026-11-02T00:00:00+09:00'}, {'timestamp': '2026-11-01T16:00:00Z'}, {'timestamp': 'invalid'}]
        self.assertEqual(last_activity(records), datetime(2026, 11, 1, 16, tzinfo=timezone.utc).timestamp())
