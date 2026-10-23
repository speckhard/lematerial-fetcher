"""Run exact production methods with fake database/HTTP/process-pool boundaries.

AST loading removes dependency imports, not method bodies. This complements the
normal dependency-backed tests; it is not a live database or process-pool test.
"""

import ast
import functools
import unittest
from abc import ABC, abstractmethod
from concurrent.futures import Future
from datetime import UTC, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3] / "src" / "lematerial_fetcher"


def load_nodes(path, names, namespace):
    tree = ast.parse(path.read_text())
    tree.body = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names
    ]
    exec(compile(tree, str(path), "exec"), namespace)  # noqa: S102 -- Execute checked-in methods only.


class ImmediatePool:
    """Deterministic Future boundary; exercise parent orchestration without forks."""

    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def shutdown(self, **kwargs):
        pass

    def submit(self, fn, *args, **kwargs):
        result = Future()
        try:
            result.set_result(fn(*args, **kwargs))
        except Exception as error:  # noqa: BLE001 -- Match Future exception storage.
            result.set_exception(error)
        return result


def fetcher_fixture(debug, responses, *, initialization_error=False, write_error=False):
    database = Mock()
    if write_error:
        database.batch_insert_data.side_effect = ValueError("write failed")
    response = Mock()
    response.json.side_effect = responses
    session = Mock()
    session.get.return_value = response
    namespace = {
        "ABC": ABC,
        "abstractmethod": abstractmethod,
        "Any": Any,
        "List": list,
        "Optional": Optional,
        "FetcherConfig": SimpleNamespace,
        "ItemsInfo": lambda **kw: SimpleNamespace(total_count=None, items=None, **kw),
        "BatchInfo": SimpleNamespace,
        "StructuresDatabase": Mock(return_value=database),
        "DatasetVersions": Mock(),
        "logger": Mock(),
        "functools": functools,
        "Manager": Mock(),
        "ProcessPoolExecutor": ImmediatePool,
        "datetime": datetime,
        "UTC": UTC,
        "create_session": Mock(return_value=session),
        "build_aflux_query": lambda url, **kw: url,
        "parse_aflowlib_date": lambda value: None,
        "RawStructure": lambda **kw: SimpleNamespace(**kw),
    }
    if initialization_error:
        namespace["StructuresDatabase"].side_effect = ValueError(
            "initialization failed"
        )
    load_nodes(ROOT / "fetch.py", {"BaseFetcher"}, namespace)
    load_nodes(ROOT / "fetcher/aflow/fetch.py", {"AflowFetcher"}, namespace)
    cls = namespace["AflowFetcher"]
    instance = object.__new__(cls)
    instance.config = SimpleNamespace(
        page_offset=0,
        page_limit=1,
        num_workers=2,
        base_url="https://example.test/",
        db_conn_str="fixture",
        table_name="fixture",
    )
    instance.debug = debug
    instance.manager = Mock()
    instance.manager_dict = {}
    instance.get_current_version = Mock(return_value=None)
    instance.setup_resources = Mock()
    instance.update_version = Mock()
    instance.cleanup_resources = Mock()
    return instance, response, namespace


class FetchFailureTests(unittest.TestCase):
    def test_only_empty_page_completes_version_in_both_modes(self):
        for debug in (True, False):
            with self.subTest(debug=debug):
                f, _, _ = fetcher_fixture(debug, [[], []])
                f.fetch()
                f.update_version.assert_called_once()

    def test_errors_cannot_publish_completed_version_in_both_modes(self):
        for debug in (True, False):
            for failure in ("http", "json", "payload", "initialization", "write"):
                with self.subTest(debug=debug, failure=failure):
                    entry = {"auid": "aflow:fixture"}
                    responses = (
                        [{"error": "API failed"}] * 3
                        if failure == "payload"
                        else [entry]
                    )
                    if failure != "payload":
                        responses = [[entry]] * 3
                    f, response, _ = fetcher_fixture(
                        debug,
                        responses,
                        initialization_error=failure == "initialization",
                        write_error=failure == "write",
                    )
                    if failure == "http":
                        response.raise_for_status.side_effect = ValueError("HTTP500")
                    if failure == "json":
                        response.json.side_effect = ValueError("malformed JSON")
                    with self.assertRaisesRegex(RuntimeError, "AFLOW fetch failed"):
                        f.fetch()
                    f.update_version.assert_not_called()

    def test_failure_after_an_inserted_page_is_not_completion(self):
        for debug in (True, False):
            with self.subTest(debug=debug):
                f, _, ns = fetcher_fixture(
                    debug,
                    [[{"auid": "aflow:fixture"}], ValueError("late JSON failure"), []],
                )
                with self.assertRaisesRegex(RuntimeError, "AFLOW fetch failed"):
                    f.fetch()
                ns["StructuresDatabase"].return_value.batch_insert_data.assert_called()
                f.update_version.assert_not_called()


class TransformPolicyTests(unittest.TestCase):
    def transform(self, dft_type="ABSENT"):
        raw = {"energy_cell": -27.0}
        if dft_type != "ABSENT":
            raw["dft_type"] = dft_type
        namespace = {
            "Any": Any,
            "OptimadeStructure": Mock(side_effect=lambda **kw: SimpleNamespace(**kw)),
            "Functional": SimpleNamespace(PBE=SimpleNamespace(value="pbe")),
            "build_structure_from_aflux": Mock(return_value="geometry"),
            "get_optimade_from_pymatgen": Mock(return_value={}),
            "parse_aflowlib_date": Mock(return_value=None),
            "datetime": datetime,
            "UTC": UTC,
            "timezone": timezone,
        }
        load_nodes(
            ROOT / "fetcher/aflow/utils.py", {"transform_aflux_entry"}, namespace
        )
        return namespace["transform_aflux_entry"](raw, "aflow:fixture"), raw

    def test_unknown_functional_not_labeled_pbe(self):
        for value in ("ABSENT", None, [], ["PAW_LDA"], ["PAW_PBE", "PAW_LDA"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.transform(value)

    def test_valid_pbe_does_not_supply_unaudited_standardized_energy(self):
        row, raw = self.transform(["PAW_PBE"])
        self.assertIsNone(row.energy)
        self.assertEqual(raw["energy_cell"], -27.0)


class ParentFailureTests(unittest.TestCase):
    def test_worker_crash_after_another_page_ends_cannot_publish(self):
        class CrashPool(ImmediatePool):
            def __init__(self, **kwargs):
                self.calls = 0

            def submit(self, fn, *args, **kwargs):
                self.calls += 1
                result = Future()
                if self.calls == 2:
                    result.set_exception(RuntimeError("worker exited before task body"))
                else:
                    result.set_result(False)
                return result

        f, _, namespace = fetcher_fixture(False, [])
        namespace["ProcessPoolExecutor"] = CrashPool
        with self.assertRaisesRegex(RuntimeError, "worker exited"):
            f.fetch()
        f.update_version.assert_not_called()
