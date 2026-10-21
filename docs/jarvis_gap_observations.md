# Reading JARVIS band gaps

This helper reads two separate observations from each raw row:

- `optb88vdw_bandgap`, in eV.
- `mbj_bandgap`, in eV.

It keeps zero gaps. Missing values stay missing. Negative values, booleans and
numeric strings are kept as raw input but are not accepted as gap labels. The
two methods have separate calculation IDs and retain the associated structure.
They must stay in the same crystal group when the training split is assigned.

For rows saved by the raw fetcher:

```python
from lematerial_fetcher.fetcher.jarvis.band_gaps import extract_stored_band_gaps
observations = extract_stored_band_gaps(raw_structure.attributes)
```

The helper separates the added `_lematerial_ingestion` receipt from the original
row before computing the row hash. It checks an existing row hash if one was
supplied and does not change the input. Published receipts must match the pinned
Figshare article, version, file, snapshot and publication dates. Those fields
remain in the output. Old or conflicting receipts fail rather than being silently
renamed. For archive rows without stored metadata, use `extract_band_gaps` with
an explicit matching receipt and raw-row hash.

These are observations, not approved training examples. All outputs retain
`training_eligible=False`. Spin, U, SOC, convergence and the electronic calculation's
reference geometry still need independent evidence. A row hash binds the current
row; it does not prove that a caller's row belongs to the original archive.
Zero total magnetization does not prove a nonmagnetic state. No formula-only
joins, MP energy corrections, gap imputation or source pooling happen here.

The structure check keeps the native lattice, elements, coordinates and explicit
fractional/Cartesian flag. It rejects invalid shapes, nonfinite coordinates,
unknown elements and singular cells. It does not convert coordinate systems or
certify that a structure is a stable crystal.

## Tests and sources

Six original tests cover gap methods, zeros, missing/invalid values, row binding
and geometry checks. Three new stored-row tests first failed because the bridge
was missing; they now pass and check receipt compatibility, date preservation,
conflicts and input immutability. These use small synthetic rows. Full source
acquisition, database ingestion and training are still separate checks.

- [NIST JARVIS](https://jarvis.nist.gov/).
- [Official property keys](https://jarvis-materials-design.github.io/dbdocs/thedownloads/).
- [Native Atoms format](https://github.com/usnistgov/jarvis/blob/master/jarvis/core/atoms.py).
- [Gap methods](https://www.nature.com/articles/sdata201882).
- [Pinned export metadata](https://api.figshare.com/v2/articles/6815699/versions/11).
