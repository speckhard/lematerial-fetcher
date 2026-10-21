# Copyright 2026 Entalpic
"""Pinned raw HSE exports. No archive extraction, property pooling or training.

Reuse existing requests runtime. No network runs at import time. The optional
CLI requires an explicit file selection and destination on approved storage.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReleaseFile:
    source: str
    release: str
    file_id: int
    url: str
    filename: str
    md5: str
    size: int
    artifact_kind: str
    method: object


FILES = {
    "aims-processed-v1": ReleaseFile(
        "all_electron_hybrid",
        "10.6084/m9.figshare.28375538.v1",
        54101633,
        "https://ndownloader.figshare.com/files/54101633",
        "processed_data.json",
        "7e0a1e96801d2af2eee2bc92610c8fb9",
        1616363,
        "published",
        None,
    ),
    "snumat-v7": ReleaseFile(
        "snumat",
        "10.6084/m9.figshare.12839240.v7",
        27536420,
        "https://ndownloader.figshare.com/files/27536420",
        "hybrid_bandgap_210413.zip",
        "c54c47eb1a27e2db46aafd74da275421",
        9296882,
        "published",
        None,
    ),
    "aims-hse06-v1": ReleaseFile(
        "all_electron_hybrid",
        "10.6084/m9.figshare.28375538.v1",
        54101624,
        "https://ndownloader.figshare.com/files/54101624",
        "hse06.db",
        "04cca55ce8e7706f6d7d67ed61d95c57",
        20647936,
        "published",
        "hse06",
    ),
    "aims-pbesol-v1": ReleaseFile(
        "all_electron_hybrid",
        "10.6084/m9.figshare.28375538.v1",
        54101630,
        "https://ndownloader.figshare.com/files/54101630",
        "pbesol.db",
        "8e58a8a2760fa15d4b44b579bae4ed71",
        27324416,
        "published",
        "pbesol",
    ),
}


def _hashes(path, expected_size):
    md5, sha = hashlib.md5(), hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            size += len(chunk)
            if size > expected_size:
                raise ValueError("file exceeds pinned size")
            md5.update(chunk)
            sha.update(chunk)
    if size != expected_size:
        raise ValueError("file size differs from pin")
    return md5.hexdigest(), sha.hexdigest()


def _atomic_receipt(path, value):
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _acquire_verified(session, spec, destination):
    if not isinstance(spec, ReleaseFile) or spec.artifact_kind not in (
        "published",
        "synthetic_fixture",
    ):
        raise ValueError("explicit release kind required")
    if spec.artifact_kind == "published" and spec not in FILES.values():
        raise ValueError("published release is not pinned")
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", spec.filename)
        or not re.fullmatch(r"[0-9a-f]{32}", spec.md5)
        or type(spec.size) is not int
        or not 0 < spec.size <= 128 * 1024 * 1024
        or not spec.url.startswith("https://")
    ):
        raise ValueError("unsafe release specification")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / spec.filename
    lockpath = destination / (spec.filename + ".lock")
    if path.is_symlink() or lockpath.is_symlink():
        raise ValueError("symlink cache refused")
    with lockpath.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.exists():
            fd, temp = tempfile.mkstemp(
                prefix=path.name + ".", suffix=".part", dir=destination
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    with session.get(
                        spec.url, stream=True, timeout=(10, 60)
                    ) as response:
                        response.raise_for_status()
                        if int(response.headers.get("content-length", 0)) > spec.size:
                            raise ValueError("advertised file exceeds pinned size")
                        received = 0
                        for chunk in response.iter_content(chunk_size=65536):
                            received += len(chunk)
                            if received > spec.size:
                                raise ValueError("download exceeds pinned size")
                            stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                actual_md5, _ = _hashes(Path(temp), spec.size)
                if actual_md5 != spec.md5:
                    raise ValueError("publisher checksum mismatch")
                os.replace(temp, path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        actual_md5, sha = _hashes(path, spec.size)
        if actual_md5 != spec.md5:
            raise ValueError("cached checksum mismatch")
        receipt = {
            "source": spec.source,
            "release": spec.release,
            "file_id": spec.file_id,
            "url": spec.url,
            "filename": spec.filename,
            "size_bytes": spec.size,
            "file_sha256": sha,
            "publisher_md5": actual_md5,
            "expected_md5": spec.md5,
            "artifact_kind": spec.artifact_kind,
            "method": spec.method,
            "scope": "verified raw export; no record/geometry/protocol eligibility audit",
        }
        _atomic_receipt(destination / (spec.filename + ".receipt.json"), receipt)
        return receipt


def acquire(session, key, destination):
    if key not in FILES:
        raise ValueError("unknown pinned HSE release")
    return _acquire_verified(session, FILES[key], destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", action="append", choices=sorted(FILES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import requests

    with requests.Session() as session:
        for key in dict.fromkeys(args.file):
            print(json.dumps(acquire(session, key, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
