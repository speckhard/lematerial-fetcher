"""AFLUX query catalogue shared by database and bounded gap acquisition."""

# Properties requested from the AFLUX API for every entry.
# `geometry`, `species`, `composition` and `positions_fractional` are enough to
# rebuild the unit cell; the rest is provenance and target data.
# Properties marked required use the AFLUX existence filter `property(*)` so that
# entries missing them (e.g. some LIB3 entries) are excluded server-side instead of
# wasting pages that the transformer would have to skip.
AFLUX_REQUIRED_PROPERTIES = [
    "geometry",
    "species",
    "composition",
    "positions_fractional",
]
AFLUX_OPTIONAL_PROPERTIES = [
    "compound",
    "spacegroup_relax",
    "auid",
    "aurl",
    "catalog",
    "aflowlib_date",
    "energy_cell",
    # DFT provenance, kept in the raw table for a future energy-correction /
    # cross-compatibility audit (AFLOW runs GGA+U with its own U values, which
    # differ from the MP-2020 assumptions; see PR discussion).
    "dft_type",
    "ldau_type",
    "ldau_TLUJ",
    "species_pp_version",
    "spin_cell",
]


def build_aflux_query(base_url: str, page: int, per_page: int) -> str:
    """Build an AFLUX request URL for one page of entries (1-based pages).

    Parameters
    ----------
    base_url : str
        The AFLUX API base URL, e.g. ``http://aflow.org/API/aflux/``.
    page : int
        1-based page number.
    per_page : int
        Number of entries per page.

    Returns
    -------
    str
        The full request URL.
    """
    # $paging(0) is a magic value in AFLUX that returns the ENTIRE result set
    # in one response, so an off-by-one here would download the whole database.
    if page < 1:
        raise ValueError(
            f"AFLUX pages are 1-based (got {page}); "
            f"$paging(0) would return the entire result set"
        )
    properties = ",".join(
        [f"{p}(*)" for p in AFLUX_REQUIRED_PROPERTIES] + AFLUX_OPTIONAL_PROPERTIES
    )
    return f"{base_url}?{properties},$paging({page},{per_page})"
