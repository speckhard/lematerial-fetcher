"""Keep a data snapshot date distinct from its export publication."""

import unittest

from lematerial_fetcher.fetcher.jarvis.release import make_receipt


class ReceiptTests(unittest.TestCase):
    def test_snapshot_and_publication_are_distinct_and_version_is_unambiguous(self):
        result = make_receipt("a" * 64)
        self.assertEqual(result["snapshot_date"], "2025-09-24")
        self.assertEqual(result["published_date"], "2026-05-09T07:44:20Z")
        self.assertEqual(result["figshare_article_id"], 6815699)
        self.assertEqual(result["figshare_version"], 11)
        self.assertEqual(result["file_id"], 64391379)
        self.assertEqual(result["release"], result["version"])
        self.assertIn("v11", result["version"])
        self.assertNotIn("release_date", result)
        self.assertEqual(result["artifact_kind"], "published")
        self.assertEqual(result["archive_sha256"], "a" * 64)

    def test_receipt_rejects_invalid_checksum(self):
        for value in [None, "abc", "z" * 64]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                make_receipt(value)

    def test_archive_keeps_public_release_constants(self):
        from lematerial_fetcher.fetcher.jarvis import archive

        self.assertEqual(archive.ARCHIVE_VERSION, make_receipt("a" * 64)["release"])
        self.assertEqual(archive.ARCHIVE_URL, make_receipt("a" * 64)["url"])
