import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from io import BytesIO
import json
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


    def test_success_sets_http_status_200(self):
        snapshot = fn.build_snapshot({}, [self.item], self.now)
        self.assertEqual(snapshot["lastHttpStatus"], 200)
        self.assertIsNone(snapshot["upstreamHttpStatus"])

    def test_429_reported_without_retry(self):
        error = HTTPError(fn.RELAY_URL, 429, "Too Many Requests", {}, None)
        with tempfile.TemporaryDirectory() as folder:
            original_path = fn.DATA_PATH
            fn.DATA_PATH = Path(folder) / "news.json"
            try:
                with patch.object(fn, "urlopen", side_effect=error) as opener:
                    self.assertEqual(fn.run(), 1)
                    self.assertEqual(opener.call_count, 1)
                snapshot = json.loads(fn.DATA_PATH.read_text(encoding="utf-8"))
                self.assertEqual(snapshot["status"], "error")
                self.assertEqual(snapshot["lastHttpStatus"], 429)
                self.assertEqual(snapshot["lastError"], "Relay HTTP 429")
            finally:
                fn.DATA_PATH = original_path

    def test_403_not_retried(self):
        error = HTTPError(fn.RELAY_URL, 403, "Forbidden", {}, None)
        with patch.object(fn, "urlopen", side_effect=error) as opener:
            with self.assertRaises(fn.RelayHTTPError):
                fn.fetch_relay(fn.RELAY_URL)
            self.assertEqual(opener.call_count, 1)

    def test_503_retried_once_and_recovers(self):
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, max_bytes): return json.dumps([self_item]).encode("utf-8")
        self_item = self.item
        error = HTTPError(fn.RELAY_URL, 503, "Service Unavailable", {}, None)
        with patch.object(fn, "urlopen", side_effect=[error, FakeResponse()]) as opener:
            with patch.object(fn, "sleep") as sleeper:
                result = fn.fetch_relay(fn.RELAY_URL)
        self.assertEqual(opener.call_count, 2)
        sleeper.assert_called_once_with(3)
        self.assertEqual(result[0]["guid"], "rss-001")

    def test_503_is_not_retried_indefinitely(self):
        error = HTTPError(fn.RELAY_URL, 503, "Service Unavailable", {}, None)
        with patch.object(fn, "urlopen", side_effect=[error, error]) as opener:
            with patch.object(fn, "sleep") as sleeper:
                with self.assertRaises(fn.RelayHTTPError):
                    fn.fetch_relay(fn.RELAY_URL)
        self.assertEqual(opener.call_count, 2)
        sleeper.assert_called_once_with(3)


    def test_wrapped_upstream_429_is_not_retried(self):
        body = BytesIO(b'{"error":"origin rejected","upstreamStatus":429}')
        error = HTTPError(fn.RELAY_URL, 502, "Bad Gateway", {"Content-Type": "application/json"}, body)
        with patch.object(fn, "urlopen", side_effect=error) as opener:
            with patch.object(fn, "sleep") as sleeper:
                with self.assertRaises(fn.RelayHTTPError) as raised:
                    fn.fetch_relay(fn.RELAY_URL)
        self.assertEqual(opener.call_count, 1)
        sleeper.assert_not_called()
        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(raised.exception.upstream_status, 429)

    def test_wrapped_429_is_saved_with_both_http_statuses(self):
        with tempfile.TemporaryDirectory() as folder:
            original_path = fn.DATA_PATH
            fn.DATA_PATH = Path(folder) / "news.json"
            try:
                error = HTTPError(fn.RELAY_URL, 502, "Bad Gateway", {},
                                  BytesIO(b'{"error":"upstream rate limit","upstreamStatus":429}'))
                with patch.object(fn, "urlopen", side_effect=error):
                    self.assertEqual(fn.run(), 1)
                data = json.loads(fn.DATA_PATH.read_text(encoding="utf-8"))
                self.assertEqual(data["lastHttpStatus"], 502)
                self.assertEqual(data["upstreamHttpStatus"], 429)
                self.assertEqual(data["lastError"], "Relay HTTP 502; upstream HTTP 429")
            finally:
                fn.DATA_PATH = original_path

if __name__ == "__main__":
    unittest.main()
