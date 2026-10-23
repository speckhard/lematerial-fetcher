# Bounded, resumable AFLOW gap acquisition — 2026-10-23

The earlier geometry acquisition lost its connection after seventeen pages. Those
legacy pages remain separate evidence; this reader never silently adopts them.
The new `lematerial_fetcher.fetcher.aflow.bounded_gaps.acquire` function is an
optional file-backed acquisition path above the AFLOW source PR. It does not
change PostgreSQL versioning or claim that an incomplete table is complete.

The existing query catalogue moved into a dependency-free `aflow.catalog`
module and remains re-exported from `aflow.utils`. Both acquisition paths use the
same geometry and provenance fields. The bounded path additionally requests
`Egap`; it retains raw species, composition, fractional positions, geometry,
DFT type, U settings, pseudopotential versions and spin fields without inventing
unknown SOC/convergence values. It does not certify source settings or trainability.

## Calling from an allocated-node runner

```python
from lematerial_fetcher.fetcher.aflow.bounded_gaps import acquire

result = acquire(output_directory, {
    'max_pages': 100,
    'per_page': 1000,
    'max_requests': 150,
    'max_reserved_bytes': 300 * 1024 * 1024,
    'max_page_bytes': 2 * 1024 * 1024,
    'max_rows': 100000,
    'attempts_per_page': 3,
    'timeout_seconds': 20,
    'deadline': absolute_unix_deadline,
}, expected_progress_sha256=previously_retained_pin_or_none)
```

These are proposed ceilings, not authorization for a job. The project controller
must approve the immutable exact configuration, allocation, storage and hard
outer process cutoff. Timeouts are cooperative around reads and backoff; the
outer cutoff is required for a stuck filesystem/read implementation. No new
runtime dependencies are needed for this path. The API endpoint is fixed HTTPS,
default TLS verification is retained, redirects are refused, and no credentials
are accepted. Failed network exception strings/response bodies are not logged.

Every attempted HTTP request reserves one request and the maximum page bytes in
atomically replaced, fsynced progress BEFORE HTTP. Charges persist across retries
and restarts; actual small responses do not refund reserved response capacity.
Exact page bytes, SHA256, row counts and query URLs are persisted. A nonblocking
advisory lock prevents cooperating callers from using the same root concurrently.
The caller controls the directory and must retain the returned progress SHA256
outside it. Resume checks that pin and every stored page before contacting AFLOW;
completed pinned pages are reused, not fetched again. The absolute deadline and
all bounds and the exact query template remain immutable on resume. A regression
reproduced accepting an old cache after query-code changes; this now fails before
any network call.

A crash with a pending reservation, an orphan page, leftover atomic temporary
file, or unconfirmed publication blocks automatic recovery. Preserve that state
and its charges, inspect it under a separately reviewed recovery procedure, and
retain an independent new pin only after reconciling what completed. Do not delete
the state to obtain another attempt. Ordinary caught transport failures retain
their charges and can retry with bounded exponential backoff inside the same
run. File sizes/regular-file checks reject symlinks and FIFOs at leaf paths;
ancestor-directory control and a filesystem timeout remain caller responsibilities.
Actual Lustre durability/concurrency semantics have not been tested here.

Identical repeated AUID records collapse in the diagnostic candidates; conflicting
versions of an AUID are excluded entirely and listed in quarantine. All original
pages remain available. An empty valid response alone sets `source_exhausted`;
a page/request/row/byte/time cap or transport/schema error is incomplete. Even an
empty final page only describes the live API query at acquisition time, not an
immutable historical AFLOW snapshot. Pagination may shift while the service changes.
Geometry validation, grouping, method-specific admission and gap normalization
are downstream gates; returned candidates are not training-ready records.

## Executed software checks

Five contracts initially failed because the new module did not exist. After
implementation they passed. A later regression demonstrated that a malformed
second record could leak the first record into candidates before the whole page
was validated; validation now completes before mutating diagnostic state. Eleven
bounded-reader tests and six inherited offline AFLOW contracts pass under
Python 3.12. The new module's tests also run with existing Python 3.9. Ruff passes.
All HTTP boundaries used fake responses. No AFLOW request, PostgreSQL integration,
HU allocation, bulk download or materials-model training was performed for these
checks.

Astra found that the per-page attempt counter reset on resume despite the global
request cap. A failing exhausted-page/resume test reproduced the extra request;
per-page charges now persist before HTTP, and exhausted pages do not fetch again.

Astra independently reran all eleven bounded tests and approved this software-only
draft after that fix. This does not authorize live acquisition or certify actual
AFLOW payloads, PostgreSQL or Lustre behavior.
