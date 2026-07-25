import unittest

from codex_sync_desktop.core.pathmap import map_path


class PathMapTests(unittest.TestCase):
    def test_maps_windows_to_mac_and_prefers_longest_prefix(self):
        mappings = {r"C:\Users\EDY": "/Users/wss", r"C:\Users\EDY\Projects": "/Volumes/Work"}
        self.assertEqual(map_path(r"C:\Users\EDY\Projects\demo", mappings), "/Volumes/Work/demo")

    def test_leaves_unmatched_path(self):
        self.assertEqual(map_path("/tmp/project", {"C:/": "/Users/me"}), "/tmp/project")


if __name__ == "__main__":
    unittest.main()
