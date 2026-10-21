# Pinned hybrid-gap source exports — 2026-10-21

Acquire both approved sources directly to approved HU storage. This is raw file
acquisition; it does not extract ZIPs, open ASE databases, normalize gaps, infer
protocol metadata or start a training run. Reuse the installed requests runtime.
No network or software installation occurs at import time.

```sh
PYTHONPATH=src python -m lematerial_fetcher.fetcher.hse_releases \
  --file snumat-v7 --file aims-hse06-v1 --file aims-pbesol-v1 \
  --output /approved/hu/storage/hse-source-files
```

Use only within the project's funded/controller-owned acquisition stage, after
quota checks. The example path is a placeholder, not a configured HU location.
There is no new global `lematerial_fetcher hse` CLI command or database ingestion
hook in this PR; the module CLI makes explicit file selections reproducible.

## Frozen file identities

| File selection | Source/version | File ID | Bytes |
| --- | --- | --- | --- |
| snumat-v7 | SNUMAT Figshare12839240v7 | 27536420 | 9,296,882 |
| aims-hse06-v1 | All-electron Figshare28375538v1 | 54101624 | 20,647,936 |
| aims-pbesol-v1 | Same all-electron source, paired lower-level export | 54101630 | 27,324,416 |

Pins (URL, size, publisher MD5, version and method) are in the checked-in catalogue.
[SNUMAT metadata](https://api.figshare.com/v2/articles/12839240/versions/7) and
[all-electron metadata](https://api.figshare.com/v2/articles/28375538/versions/1)
were inspected for the parent project's 2026-10-20 source manifest. Those pinned
identities were reused; this change does not claim a new live data validation.
Retain attribution and source licenses when publishing derived data. Processed
CSV/JSON alternate views are deliberately excluded to avoid counting copies as
new observations. Published cohort size is not a usable-label count.

Each cache is size/checksum revalidated, protected by an exclusive per-file lock,
and published atomically after verification. Interrupted, oversized, wrong-size
or checksum-failing transfers remove their partial file. Completed caches are
reusable; partial HTTP-range resume is not implemented. No silent replacement of
a corrupted existing export occurs. Read/connect timeouts are explicit; use a
bounded scheduler walltime for the whole acquisition stage.

A sidecar records file ID, source/version, method, byte count, publisher MD5 and
computed SHA256. It is compatible with the existing project's local SNUMAT and
all-electron readers. File verification is not record-level geometry/protocol
verification. Receipt output follows successful acquisition; a crash after file
publication but before receipt publication can be recovered by rechecking the
cached file. No source archive is extracted here.

## Training integration remains a separate gate

Preserve both HSE sources and their method-specific output selectors. Pair only
verified geometry/protocol observations, retain PBE/PBEsol supervision, deduplicate
alternate export copies and group aliases before split assignment. Unknown U,
spin, SOC and convergence remain unknown. Weighted HSE training is not a weighted
single scalar silently mixing PBE and HSE. The parent project already has local
readers; live schema/receipt evidence must still be checked on acquired sources.

## TDD and validation

Five new tests failed before this module existed, then passed after implementation.
Fixtures exercise complete cache reuse and corruption, interruption, size/hash
failure, safe identity selection, sidecar integrity and explicit synthetic status.
Combined JARVIS raw/gap and HSE tests: 24 passed, one ijson dependency skip.
Ruff checks/formatting run on the new HSE module and tests. No published source
file, production database or model training was exercised. No new dependencies.
