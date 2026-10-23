"""Bounded AFLUX gap/geometry acquisition, independent of PostgreSQL.

Run under an allocated-node process timeout. Resume requires an externally
retained progress pin; interrupted pending requests require explicit recovery.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import stat
import time
import urllib.error
import urllib.request
from pathlib import Path

from lematerial_fetcher.fetcher.aflow.catalog import build_aflux_query

BASE_URL = "https://aflow.org/API/aflux/"


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _decode(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Nonfinite JSON")
        return result

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_float=number,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")),
    )


def _read(path, cap):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("Regular file required")
        raw = handle.read(cap + 1)
    if len(raw) > cap:
        raise ValueError("File byte cap")
    return raw


def _atomic(path, raw):
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError("Redirect refused")


def acquire(
    directory,
    limits,
    *,
    expected_progress_sha256=None,
    opener=None,
    clock=time.time,
    sleep=time.sleep,
):
    """Fetch a bounded ordered prefix, retaining exact bytes and explicit settings.

    Returns a progress pin and diagnostic candidates, not training admission.
    Config is immutable on resume, including absolute Unix deadline. Completed
    pages are hash-verified before reuse. Request/maximum-response-byte charges
    persist BEFORE HTTP and are never refunded. No credentials are accepted.
    """
    required = {
        "max_pages",
        "per_page",
        "max_requests",
        "max_reserved_bytes",
        "max_page_bytes",
        "max_rows",
        "attempts_per_page",
        "timeout_seconds",
        "deadline",
    }
    if set(limits) != required:
        raise ValueError("Exact limits required")
    for key in required - {"deadline", "timeout_seconds"}:
        if type(limits[key]) is not int or limits[key] < 1:
            raise ValueError("Positive integer bound required")
    if (
        limits["max_pages"] > 100
        or limits["per_page"] > 1000
        or limits["max_requests"] > 300
        or limits["max_rows"] > 100000
        or limits["max_page_bytes"] > 8 * 1024 * 1024
        or limits["max_reserved_bytes"] > 1024**3
        or limits["attempts_per_page"] > 3
    ):
        raise ValueError("Acquisition ceiling")
    for key in ("deadline", "timeout_seconds"):
        if (
            type(limits[key]) not in (int, float)
            or not math.isfinite(limits[key])
            or limits[key] <= 0
        ):
            raise ValueError("Finite positive time required")
    if limits["deadline"] <= clock() or limits["timeout_seconds"] > 120:
        raise ValueError("Deadline/timeout bound")
    root = Path(directory)
    if root.is_symlink():
        raise ValueError("Symlink root refused")
    root.mkdir(parents=True, exist_ok=True)
    lockfd = os.open(
        root / "acquisition.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
    )
    with os.fdopen(lockfd, "r+") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError("Regular lock required")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _acquire(root, limits, expected_progress_sha256, opener, clock, sleep)


def _acquire(root, limits, pin, opener, clock, sleep):
    def query(page):
        return build_aflux_query(BASE_URL, page, limits["per_page"]).replace(
            ",$paging", ",Egap,$paging"
        )

    path = root / "progress.json"
    if path.exists() or path.is_symlink():
        raw = _read(path, 1024 * 1024)
        if pin is None or _digest(raw) != pin:
            raise ValueError("External progress pin required")
        progress = _decode(raw)
        if (
            progress["limits"] != limits
            or progress["query_base"] != BASE_URL
            or progress.get("query_template") != query(1)
        ):
            raise ValueError("Immutable acquisition context changed")
    else:
        if pin is not None or any(root.glob("page-*")):
            raise ValueError("Unpinned existing acquisition")
        progress = {
            "version": 1,
            "limits": limits,
            "query_base": BASE_URL,
            "query_template": query(1),
            "pages": [],
            "requests": 0,
            "page_attempts": {},
            "reserved_bytes": 0,
            "pending": False,
            "source_exhausted": False,
            "stop_reason": "new",
        }

    def persist():
        raw = _json(progress)
        _atomic(path, raw)
        return _digest(raw)

    seen = {}
    conflicts = set()
    rows = 0

    def consume(raw):
        nonlocal rows
        records = _decode(raw)
        if not isinstance(records, list) or len(records) > limits["per_page"]:
            raise ValueError("Invalid AFLUX page")
        for record in records:
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("auid"), str)
                or not record["auid"].strip()
            ):
                raise ValueError("Explicit auid required")
        if rows + len(records) > limits["max_rows"]:
            raise ValueError("Row cap")
        for record in records:
            identity = record["auid"]
            if identity in seen and seen[identity] != record:
                conflicts.add(identity)
            else:
                seen[identity] = record
        rows += len(records)
        if rows > limits["max_rows"]:
            raise ValueError("Row cap")
        return len(records)

    for index, receipt in enumerate(progress["pages"], 1):
        if (
            receipt["page"] != index
            or receipt["path"] != f"page-{index:05d}.json"
            or receipt["query"] != query(index)
        ):
            raise ValueError("Page sequence mismatch")
        raw = _read(root / receipt["path"], limits["max_page_bytes"])
        if _digest(raw) != receipt["sha256"] or len(raw) != receipt["bytes"]:
            raise ValueError("Stored page changed")
        if consume(raw) != receipt["rows"]:
            raise ValueError("Stored count changed")
    if progress["pending"]:
        raise ValueError("Unconfirmed request; recovery required, no automatic refetch")
    if opener is None:
        opener = urllib.request.build_opener(_NoRedirect()).open
    while (
        not progress["source_exhausted"]
        and len(progress["pages"]) < limits["max_pages"]
    ):
        page = len(progress["pages"]) + 1
        filename = f"page-{page:05d}.json"
        if (root / filename).exists() or (root / filename).is_symlink():
            raise ValueError("Unpinned orphan page; recovery required")
        if rows + limits["per_page"] > limits["max_rows"]:
            progress["stop_reason"] = "row_cap"
            break
        completed = False
        used_attempts = progress["page_attempts"].get(str(page), 0)
        if used_attempts >= limits["attempts_per_page"]:
            progress["stop_reason"] = "page_attempt_cap"
            break
        for attempt in range(used_attempts, limits["attempts_per_page"]):
            remaining = limits["deadline"] - clock()
            if remaining <= 0:
                progress["stop_reason"] = "deadline"
                break
            if (
                progress["requests"] >= limits["max_requests"]
                or progress["reserved_bytes"] + limits["max_page_bytes"]
                > limits["max_reserved_bytes"]
            ):
                progress["stop_reason"] = "request_or_byte_cap"
                break
            progress["page_attempts"][str(page)] = attempt + 1
            progress["requests"] += 1
            progress["reserved_bytes"] += limits["max_page_bytes"]
            progress["pending"] = True
            persist()
            url = query(page)
            try:
                request = urllib.request.Request(
                    url, headers={"Accept-Encoding": "identity"}
                )
                with opener(
                    request, timeout=min(limits["timeout_seconds"], remaining)
                ) as response:
                    if (
                        response.status != 200
                        or response.headers.get("Content-Encoding", "identity")
                        != "identity"
                    ):
                        raise ValueError("HTTP status/encoding")
                    raw = bytearray()
                    while True:
                        if clock() >= limits["deadline"]:
                            raise ValueError("Read deadline")
                        block = response.read(
                            min(65536, limits["max_page_bytes"] + 1 - len(raw))
                        )
                        if not block:
                            break
                        raw.extend(block)
                        if len(raw) > limits["max_page_bytes"]:
                            raise ValueError("Response cap")
                    raw = bytes(raw)
                count = consume(raw)
            except (OSError, urllib.error.URLError):
                progress["pending"] = False
                progress["stop_reason"] = "transport_error"
                persist()
                if attempt + 1 < limits["attempts_per_page"]:
                    sleep(min(2**attempt, max(0, limits["deadline"] - clock())))
                continue
            except (ValueError, TypeError):
                progress["pending"] = False
                progress["stop_reason"] = "invalid_response"
                persist()
                break
            _atomic(root / filename, raw)
            progress["pages"].append(
                {
                    "page": page,
                    "path": filename,
                    "sha256": _digest(raw),
                    "bytes": len(raw),
                    "rows": count,
                    "query": url,
                }
            )
            progress["pending"] = False
            progress["source_exhausted"] = count == 0
            progress["stop_reason"] = "empty_page" if count == 0 else "page_cap"
            persist()
            completed = True
            break
        if not completed:
            break
    pin = persist()
    candidates = [
        record for identity, record in seen.items() if identity not in conflicts
    ]
    return {
        "progress_sha256": pin,
        "requests": progress["requests"],
        "reserved_bytes": progress["reserved_bytes"],
        "pages": len(progress["pages"]),
        "source_rows": rows,
        "candidate_rows": len(candidates),
        "conflicting_ids": sorted(conflicts),
        "source_exhausted": progress["source_exhausted"],
        "stop_reason": progress["stop_reason"],
        "candidates": candidates,
        "scope": "ordered_prefix_not_training_admission",
    }
