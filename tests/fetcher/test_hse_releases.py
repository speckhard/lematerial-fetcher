"""Bounded synthetic byte streams; no network or published data fixtures."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lematerial_fetcher.fetcher.hse_releases import (
    FILES,
    ReleaseFile,
    _acquire_verified,
    acquire,
)


class Response:
    def __init__(self, data, fail=False):
        self.data = data
        self.fail = fail
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.data[:2]
        if self.fail:
            raise OSError("fixture interruption")
        yield self.data[2:]


class Session:
    def __init__(self, data, fail=False):
        self.data = data
        self.fail = fail
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        assert kwargs["timeout"] == (10, 60)
        return Response(self.data, self.fail)


def fixture(data=b"fixture"):
    return ReleaseFile(
        "snumat",
        "synthetic-only",
        123,
        "https://example.test/fixture",
        "fixture.zip",
        hashlib.md5(data).hexdigest(),
        len(data),
        "synthetic_fixture",
        None,
    )


class HseReleaseTests(unittest.TestCase):
    def test_catalog_has_both_sources_and_both_aims_methods(self):
        self.assertEqual(set(FILES), {"snumat-v7", "aims-hse06-v1", "aims-pbesol-v1"})
        self.assertEqual(FILES["aims-hse06-v1"].method, "hse06")
        self.assertEqual(FILES["aims-pbesol-v1"].method, "pbesol")
        self.assertEqual(FILES["snumat-v7"].file_id, 27536420)

    def test_verified_atomic_artifact_and_reader_compatible_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _acquire_verified(Session(b"fixture"), fixture(), Path(tmp))
            self.assertEqual(
                result["file_sha256"], hashlib.sha256(b"fixture").hexdigest()
            )
            self.assertEqual(result["artifact_kind"], "synthetic_fixture")
            self.assertEqual(result["source"], "snumat")
            self.assertEqual((Path(tmp) / "fixture.zip").read_bytes(), b"fixture")
            self.assertEqual(
                json.loads((Path(tmp) / "fixture.zip.receipt.json").read_text()), result
            )
            self.assertEqual(list(Path(tmp).glob("*.part")), [])

    def test_interrupt_wrong_size_and_checksum_publish_nothing(self):
        for data, fail in [
            (b"fixture", True),
            (b"too-long", False),
            (b"wrongxx", False),
        ]:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises((OSError, ValueError)):
                    _acquire_verified(Session(data, fail), fixture(), Path(tmp))
                self.assertFalse((Path(tmp) / "fixture.zip").exists())
                self.assertEqual(list(Path(tmp).glob("*.part")), [])
                self.assertFalse((Path(tmp) / "fixture.zip.receipt.json").exists())

    def test_cache_rechecked_no_network_and_corruption_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Session(b"fixture")
            _acquire_verified(session, fixture(), Path(tmp))
            _acquire_verified(session, fixture(), Path(tmp))
            self.assertEqual(session.calls, 1)
            (Path(tmp) / "fixture.zip").write_bytes(b"wrongxx")
            with self.assertRaises(ValueError):
                _acquire_verified(session, fixture(), Path(tmp))
            self.assertEqual(session.calls, 1)

    def test_unknown_release_and_unsafe_filename_fail_before_request(self):
        session = Session(b"fixture")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                acquire(session, "latest-unpinned", tmp)
            from dataclasses import replace

            with self.assertRaises(ValueError):
                _acquire_verified(
                    session, replace(fixture(), filename="../escape"), Path(tmp)
                )
            self.assertEqual(session.calls, 0)
