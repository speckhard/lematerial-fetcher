"""Offline contracts; no HTTP or material database dependencies."""

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

PATH = (
    Path(__file__).resolve().parents[3]
    / "src/lematerial_fetcher/fetcher/aflow/bounded_gaps.py"
)


def module():
    spec = importlib.util.spec_from_file_location("bounded_gaps", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Response(io.BytesIO):
    status = 200

    def __init__(self, raw):
        super().__init__(raw)
        self.headers = {"Content-Encoding": "identity"}


class Contracts(unittest.TestCase):
    def config(self):
        return {
            "max_pages": 3,
            "per_page": 2,
            "max_requests": 6,
            "max_reserved_bytes": 60000,
            "max_page_bytes": 10000,
            "max_rows": 6,
            "attempts_per_page": 2,
            "timeout_seconds": 2,
            "deadline": 1000,
        }

    def run_fake(self, root, results, **kwargs):
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            result = results.pop(0)
            if isinstance(result, Exception):
                raise result
            return Response(json.dumps(result).encode())

        result = module().acquire(
            root,
            self.config(),
            opener=opener,
            clock=lambda: 100,
            sleep=lambda _: None,
            **kwargs,
        )
        return result, calls

    def test_pages_resume_without_refetch_and_geometry_query(self):
        with tempfile.TemporaryDirectory() as root:
            result, calls = self.run_fake(root, [[{"auid": "aflow:a"}], []])
            self.assertTrue(result["source_exhausted"])
            self.assertEqual(len(calls), 2)
            for field in (
                "geometry(*)",
                "positions_fractional(*)",
                "Egap",
                "dft_type",
                "ldau_TLUJ",
            ):
                self.assertIn(field, calls[0])
            again, calls = self.run_fake(
                root, [], expected_progress_sha256=result["progress_sha256"]
            )
            self.assertEqual(calls, [])
            self.assertEqual(again["requests"], 2)

    def test_retry_budget_and_conflict_quarantine(self):
        with tempfile.TemporaryDirectory() as root:
            result, calls = self.run_fake(
                root,
                [
                    OSError("secret"),
                    [{"auid": "a", "Egap": 1}],
                    [{"auid": "a", "Egap": 2}],
                    [],
                ],
            )
            self.assertEqual(len(calls), 4)
            self.assertEqual(result["conflicting_ids"], ["a"])
            self.assertEqual(result["candidate_rows"], 0)
            self.assertEqual(result["requests"], 4)

    def test_external_pin_and_corrupt_page_block_network(self):
        with tempfile.TemporaryDirectory() as root:
            result, _ = self.run_fake(root, [[]])
            with self.assertRaises(ValueError):
                self.run_fake(root, [])
            Path(root, "page-00001.json").write_text("[] ")
            with self.assertRaises(ValueError):
                self.run_fake(
                    root, [], expected_progress_sha256=result["progress_sha256"]
                )

    def test_failure_is_incomplete_not_exhausted(self):
        with tempfile.TemporaryDirectory() as root:
            result, calls = self.run_fake(root, [OSError("token"), OSError("token")])
            self.assertEqual(len(calls), 2)
            self.assertFalse(result["source_exhausted"])
            self.assertEqual(result["stop_reason"], "transport_error")
            self.assertNotIn("token", json.dumps(result))

    def test_invalid_page_does_not_publish_partial_candidates(self):
        with tempfile.TemporaryDirectory() as root:
            result, _ = self.run_fake(root, [[{"auid": "a"}, {"missing": "auid"}]])
            self.assertEqual(result["candidate_rows"], 0)
            self.assertEqual(result["source_rows"], 0)
            self.assertEqual(result["stop_reason"], "invalid_response")

    def test_interrupted_request_keeps_charge_and_blocks_resume(self):
        with tempfile.TemporaryDirectory() as root:

            def interrupted(*_a, **_k):
                raise KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                module().acquire(
                    root, self.config(), opener=interrupted, clock=lambda: 100
                )
            raw = Path(root, "progress.json").read_bytes()
            import hashlib

            progress = json.loads(raw)
            self.assertEqual(progress["requests"], 1)
            self.assertTrue(progress["pending"])
            with self.assertRaisesRegex(ValueError, "Unconfirmed"):
                self.run_fake(
                    root, [], expected_progress_sha256=hashlib.sha256(raw).hexdigest()
                )

    def test_exhausted_page_attempts_remain_exhausted_after_resume(self):
        with tempfile.TemporaryDirectory() as root:
            result, calls = self.run_fake(root, [OSError("failed"), OSError("failed")])
            self.assertEqual(len(calls), 2)
            resumed, calls = self.run_fake(
                root, [], expected_progress_sha256=result["progress_sha256"]
            )
            self.assertEqual(calls, [])
            self.assertEqual(resumed["requests"], 2)
            self.assertFalse(resumed["source_exhausted"])

    def test_changed_query_code_cannot_resume_old_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            result, _ = self.run_fake(root, [[]])
            mod = module()
            mod.build_aflux_query = lambda *_a: "https://aflow.org/API/aflux/?changed"
            with self.assertRaisesRegex(ValueError, "context"):
                mod.acquire(
                    root,
                    self.config(),
                    expected_progress_sha256=result["progress_sha256"],
                    opener=lambda *_a, **_k: self.fail("network"),
                    clock=lambda: 100,
                )

    def test_page_byte_cap_and_nonfinite_are_terminal(self):
        for rows in (
            [{"auid": "a", "huge": "x" * 12000}],
            [{"auid": "a", "gap": float("inf")}],
        ):
            with (
                self.subTest(rows=str(rows)[:30]),
                tempfile.TemporaryDirectory() as root,
            ):
                result, calls = self.run_fake(root, [rows])
                self.assertEqual(result["pages"], 0)
                self.assertEqual(result["candidate_rows"], 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual(result["stop_reason"], "invalid_response")

    def test_page_cap_is_not_source_completion(self):
        with tempfile.TemporaryDirectory() as root:
            result, calls = self.run_fake(root, [[{"auid": str(i)}] for i in range(3)])
            self.assertEqual(len(calls), 3)
            self.assertFalse(result["source_exhausted"])
            self.assertEqual(result["stop_reason"], "page_cap")

    def test_caps_and_pending_reservation_stop_fetch(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.config()
            config["deadline"] = 99
            with self.assertRaises(ValueError):
                module().acquire(
                    root,
                    config,
                    opener=lambda *_a, **_k: self.fail("network"),
                    clock=lambda: 100,
                )


if __name__ == "__main__":
    unittest.main()
