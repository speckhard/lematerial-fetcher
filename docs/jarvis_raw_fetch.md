# JARVIS-DFT raw archive connector

This draft adds `lematerial_fetcher jarvis fetch`. It ingests the official JARVIS
3D DFT Figshare archive into a **fresh PostgreSQL raw table**. It does not yet
transform JARVIS records into the common LeMaterial property schema or upload a
new dataset. OPTIMADE exposes structure metadata but not the gap/elastic fields
needed here, so this connector uses the published bulk archive.

## Source and scope

- [JARVIS-DFT](https://jarvis.nist.gov/) and [official downloader](https://github.com/usnistgov/jarvis/blob/master/jarvis/db/figshare.py).
- [Figshare article](https://api.figshare.com/v2/articles/6815699), version 11 metadata inspected 2026-10-20; CC BY 4.0.
- `jdft_3d-9-24-2025.json.zip`, file `64391379`, published size 48,447,610 bytes.
- Publisher MD5 `c3179161ef0d029cf1fa70da463aac6e`; SHA256 also saved in each ingestion receipt.

The archive pin is explicit. Changing releases requires reviewing the file,
checksum and release constants together. The MD5 is a publisher identity check,
not an independent authenticity guarantee. HTTPS certificate verification stays
on through the existing session helper.

Raw attributes preserve separate `optb88vdw_bandgap`, `mbj_bandgap`, elastic
fields, missing-value representations and all other source fields. Zero gaps
remain zero. No PBE relabeling, MP energy corrections, unit conversion or
cross-source deduplication is performed. `last_modified` is null because the
snapshot date is not an entry modification timestamp. `_lematerial_ingestion`
keeps the snapshot date, Figshare article/version and publication timestamp separately. Parsed values preserve field semantics,
not byte-for-byte JSON formatting; hashes identify the original archive.

## Operation

Use the project's existing database configuration; keep credentials out of
command history. Choose a fresh table for each successful import:

```bash
lematerial_fetcher --cache-dir /approved/storage/cache jarvis fetch \
  --table-name jarvis_dft_20250924 --limit 500 --offset 0
```

`--limit` controls database batch size, **not total records downloaded**;
`--offset` must be zero. This is one streaming archive task; worker-count options
have no effect. The verified compressed archive is cached, capped at 128 MiB;
the single JSON member is capped at 2 GiB. Production parsing uses the project's
existing `ijson` dependency. Database batches are bounded, though a set of seen
JIDs grows with the archive for duplicate detection. Budget disk for archive,
raw JSONB data and PostgreSQL indexes before running; no laptop bulk import is
needed. No software is installed by the connector.

Committed batches go only to a unique `jarvis_stage_<uuid>` table. Only after
complete parsing and insertion does one transaction rename that table and write
its completed dataset version. Existing destination tables are refused; a
concurrent publisher also fails safely at rename. No prior table is overwritten.
Ordinary errors roll back publication, drop staging and close connections.
Retry a failed import from the verified cache into a fresh destination. A hard
process kill can leave an orphan staging table: inspect active imports and its
contents before an administrator explicitly drops that exact orphan. Never drop
staging tables belonging to an active process. Cleanup failures can leave a
stage and obscure an earlier error; neither counts as completed ingestion.

## Verification and remaining gates

Small offline fixtures cover raw field retention, checksum/size rejection,
interrupted downloads, duplicate identities, array roots, bounded insertion,
late parsing failure, stage cleanup and transactional publication call ordering.
They use mocked database connections, **not a live PostgreSQL atomicity test**.

```bash
PYTHONPATH=src python -m unittest discover -s tests/fetcher/jarvis
```

Local result: 14 tests, 13 passed and one skipped because `ijson` is unavailable
in the existing offline runtime. The production-parser test runs with upstream
runtime dependencies and checks valid, truncated, trailing and wrong-root JSON.
GitHub CI subsequently installed the upstream dependencies and passed lint plus
the full suite: **145 passed, 2 skipped** (the two skips are outside JARVIS). All
14 JARVIS tests, including the production-parser fixtures, passed there. See
[CI run](https://github.com/LeMaterial/lematerial-fetcher/actions/runs/39421761489).
The parser now receives a binary ZIP stream. A small regression checks that
boundary; the actual ijson test still needs the installed dependency. No real archive import,
JARVIS-specific dependency-backed CLI smoke, live PostgreSQL or concurrent
publication check was performed. These remain required before production use;
this is deliberately a draft raw-ingestion PR.
No new dependencies were added. Parser syntax and lint checks passed locally.

TDD evidence: archive/store fixture tests failed before their implementations;
publication tests failed with missing `publish` and then missing `ingest` before
those implementations. Relevant offline regressions passed afterwards. An
adversarial Astra review found the initial partial-table publication issue;
staging plus atomic version publication addresses it, with integration limits
above explicitly retained.

## Review fixes — 2026-10-21

The filename describes a 2025-09-24 snapshot. Figshare article6815699 version11
was published on 2026-05-09T07:44:20Z. These are different dates. Receipts now
store both, with file64391379 and its checksum. The release ID names the article,
version and file instead of calling the snapshot date a publication date.
[Exact source metadata](https://api.figshare.com/v2/articles/6815699/versions/11).

Archive URL/version exports remain available for existing callers. Old receipts
are not rewritten. Their legacy version name is not silently promoted to the
new audited format; downstream readers must keep or explicitly migrate them.

Tests first: release-receipt tests failed before the helper existed. A binary
stream test failed on the old text wrapper. Both now pass. A public-constant
regression caught a removed re-export during cleanup and now passes too. The
raw-source suite has17 passes and one missing-ijson skip. No live database or
source download was run.
