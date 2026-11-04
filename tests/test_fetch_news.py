import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_news as fn

class FetchNewsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 4, 7, 0, 0, tzinfo=timezone.utc)
        self.item = {
            "guid": "rss-001", "title": "Test headline",
            "link": "https://www.financialjuice.com/news/test",
            "pubDate": "Wed, 04 Nov 2026 06:35:00 GMT",
            "description": "Demo item only",
        }

    def test_new_items_and_metadata(self):
        snapshot = fn.build_snapshot({}, [self.item], self.now)
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["articleCount"], 1)
        self.assertEqual(snapshot["articles"][0]["guid"], "rss-001")

    def test_duplicate_guid_is_replaced(self):
        first = fn.build_snapshot({}, [self.item], self.now)
        second = fn.build_snapshot(first, [{**self.item, "title": "Corrected"}], self.now)
        self.assertEqual(second["articleCount"], 1)
        self.assertEqual(second["articles"][0]["title"], "Corrected")

    def test_bad_pubdate_rejected(self):
        with self.assertRaises(ValueError):
            fn.clean_record({**self.item, "pubDate": "invalid"})

    def test_failure_preserves_articles_and_marks_error(self):
        ok = fn.build_snapshot({}, [self.item], self.now)
        failed = fn.build_failure(ok, self.now, "TimeoutError")
        self.assertEqual(failed["status"], "error")
        self.assertEqual(failed["articles"], ok["articles"])

    def test_older_articles_are_dropped(self):
        old = {**self.item, "guid": "old", "pubDate": "Tue, 03 Nov 2026 06:35:00 GMT"}
        self.assertEqual(fn.build_snapshot({}, [old, self.item], self.now)["articleCount"], 1)

    def test_snapshot_can_be_written(self):
        with tempfile.TemporaryDirectory() as folder:
            original_path = fn.DATA_PATH
            fn.DATA_PATH = Path(folder) / "news.json"
            try:
                data = fn.build_snapshot({}, [self.item], self.now)
                fn.DATA_PATH.write_text("{}")
                self.assertEqual(fn.read_existing(), {})
            finally:
                fn.DATA_PATH = original_path

if __name__ == "__main__":
    unittest.main()
