# JARVIS band-gap observations — 2026-10-21

`extract_band_gaps(raw, receipt)` extracts optB88vdW and TBmBJ as separate eV
observations. It does not manufacture missing values, infer nonmagnetism from
zero total moment, or certify an independently verified calculation/structure
binding. All outputs have `training_eligible=False` until downstream audits.
This is an observation envelope, not an OPTIMADE structure transformer, a
completed project training adapter, or an elastic-property implementation.

Raw row and associated native atoms are retained by hash; the receipt declares
the pinned raw archive and record identity. The function checks canonical row
hashes, full native atom shape/count/basis, finite coordinates and nonsingular
lattices. It does not prove caller receipts truthful or retrieve VASP inputs.
No formula-only joins, element filtering, split assignment, source pooling or
MP corrections occur here. Unknown U/SOC/spin/convergence stay unknown. Both
method variants need the same split group downstream; distinct calculation IDs
must not be interpreted as distinct independent crystals.

The returned gap mask means a valid scalar observation, not training eligibility.
Numeric strings, negative, boolean or nonfinite gaps are not accepted as numbers;
known null/NA placeholders stay missing. Zero is a valid gap. Full archive rows
with non-JSON finite values fail hashing rather than silently changing input.
Native atom properties are copied, with geometry hash restricted to explicit
lattice/species/coordinates/basis; no hidden fractional/Cartesian conversion.

Evidence and sources:

- [NIST JARVIS](https://jarvis.nist.gov/): distinct electronic gap methods, including SOC variants.
- [Official download field list](https://jarvis-materials-design.github.io/dbdocs/thedownloads/): `optb88vdw_bandgap`, `mbj_bandgap` and `atoms`.
- [JARVIS Atoms implementation](https://github.com/usnistgov/jarvis/blob/master/jarvis/core/atoms.py): explicit coordinate basis and native structure schema.
- [Method descriptor](https://www.nature.com/articles/sdata201882): electronic gaps in eV; method distinction matters.

TDD: six new fixture tests failed collection before `band_gaps.py` existed, then
passed after implementation. Combined raw/archive/publication/gap suite:
19 passed, one production-parser dependency skip. These are tiny synthetic
fixtures, not corpus coverage or real recovered training labels. Full dependency
suite and live ingestion remain open. No new dependencies or bulk downloads.
