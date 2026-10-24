# Downloading the two HSE datasets

This command downloads SNUMAT and the all-electron HSE06/PBEsol exports. Run it
on approved HU storage after checking the job budget and free space:

```sh
PYTHONPATH=src python -m lematerial_fetcher.fetcher.hse_releases \
  --file snumat-v7 --file aims-hse06-v1 --file aims-pbesol-v1 \
  --output /approved/hu/storage/hse-source-files
```

Replace the example output path. The command does not unpack ZIPs, open the
structure databases or train a model. It uses the project's existing requests
package. No network request happens when the module is imported or when help is
shown. There is no global `lematerial_fetcher hse` database command yet.

| Selection | Source version | File ID | Download bytes |
| --- | --- | --- | --- |
| snumat-v7 | Figshare12839240v7 | 27536420 | 9,296,882 |
| aims-hse06-v1 | Figshare28375538v1 | 54101624 | 20,647,936 |
| aims-pbesol-v1 | Same source, lower-level calculation | 54101630 | 27,324,416 |

The code pins each file's URL, size, publisher checksum and version. Source
metadata: [SNUMAT](https://api.figshare.com/v2/articles/12839240/versions/7) and
[all-electron hybrid](https://api.figshare.com/v2/articles/28375538/versions/1).
Keep their attribution and licenses with derived datasets. CSV/JSON copies of
the same records are not additional materials.

Downloads have explicit timeouts and exact size/checksum checks. A completed file
is renamed into place only after verification. Interrupted or invalid transfers
leave no published partial file. A file lock prevents two writers using the same
cache. An existing complete file is checked again and reused; a corrupt existing
file causes an error. Partial HTTP-range resume is not implemented. Use a bounded
job walltime for the whole download stage.

Each file gets a JSON receipt with its source/version, method, file ID, byte
count, publisher MD5 and computed SHA256. These fields match the parent project's
existing local HSE readers. If a process stops between file and receipt writes,
a retry checks the cached file and recreates the receipt. No published source
file was downloaded during the local tests.

## Before training

The two datasets have different calculation settings. Keep those settings and
source-specific outputs; do not call a weighted PBE/HSE average an HSE prediction.
Inspect the actual records, match structures carefully and keep copies of one
crystal in the same split. Unknown spin, U, SOC and convergence stay unknown.
A checksum proves file identity, not record eligibility or model accuracy.

Both approved HSE sources must be audited for the combined milestone. A usable
single-source baseline is clearly labeled as partial if the other source fails.
Fine-tuning and matched-pair delta learning remain later comparisons.

## Tests and review follow-up

Five acquisition tests first failed because the module was missing, then passed.
They use tiny synthetic byte streams to check interruption, wrong size/checksum,
cache corruption/reuse, safe file selection and receipt fields. The module help
also runs under the existing Python3.12. No software was installed.

PR4 now includes the corrected AFLOW/JARVIS branches below it. Review found no
separate HSE acquisition bug requiring a change to its download code. Full-runtime
source ingestion, actual file-to-reader checks and training remain separate work.
