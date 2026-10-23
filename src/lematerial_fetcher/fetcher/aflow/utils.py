# Copyright 2025 Entalpic
from datetime import UTC, datetime
from typing import Any

from pymatgen.core import Lattice, Structure

from lematerial_fetcher.fetcher.aflow.catalog import (
    AFLUX_OPTIONAL_PROPERTIES,
    AFLUX_REQUIRED_PROPERTIES,
    build_aflux_query,
)
from lematerial_fetcher.models.optimade import Functional, OptimadeStructure
from lematerial_fetcher.utils.structure import get_optimade_from_pymatgen

__all__ = [
    "AFLUX_OPTIONAL_PROPERTIES",
    "AFLUX_REQUIRED_PROPERTIES",
    "build_aflux_query",
    "build_structure_from_aflux",
    "parse_aflowlib_date",
    "transform_aflux_entry",
]


def parse_aflowlib_date(raw: Any) -> datetime | None:
    """Parse an AFLOW ``aflowlib_date`` value (e.g. ``20200426_10:04:20_GMT-5``).

    The timezone suffix is ignored; day-level precision is enough for versioning.
    """
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[-1] if raw else None
        if not raw:
            return None
    try:
        return datetime.strptime(str(raw)[:17], "%Y%m%d_%H:%M:%S")  # noqa: DTZ007 -- Retain source calendar date, not a UTC timestamp.
    except ValueError:
        return None


def build_structure_from_aflux(attributes: dict[str, Any]) -> Structure:
    """Rebuild a pymatgen Structure from AFLUX geometry properties.

    - ``geometry``             : [a, b, c, alpha, beta, gamma]
    - ``species``              : unique elements, in POSCAR order
    - ``composition``          : per-species atom counts, aligned with ``species``
    - ``positions_fractional`` : fractional coordinates, in the same species order
    """
    a, b, c, alpha, beta, gamma = [float(x) for x in attributes["geometry"]]
    lattice = Lattice.from_parameters(a, b, c, alpha, beta, gamma)

    species = attributes["species"]
    if isinstance(species, str):
        species = [s for s in species.split(",") if s]

    composition = attributes["composition"]
    if isinstance(composition, str):
        composition = [int(float(x)) for x in composition.split(",") if x]
    else:
        composition = [int(float(x)) for x in composition]

    species_at_sites: list[str] = []
    for element, count in zip(species, composition):
        species_at_sites.extend([element] * count)

    positions = attributes["positions_fractional"]
    if len(species_at_sites) != len(positions):
        raise ValueError(
            f"Site count mismatch: sum(composition)={len(species_at_sites)} "
            f"!= len(positions_fractional)={len(positions)}"
        )

    return Structure(lattice, species_at_sites, positions, coords_are_cartesian=False)


def transform_aflux_entry(
    attributes: dict[str, Any], entry_id: str
) -> OptimadeStructure:
    """Transform one raw AFLUX entry into an OptimadeStructure.

    Parameters
    ----------
    attributes : dict
        The raw AFLUX entry (as stored in ``RawStructure.attributes``).
    entry_id : str
        The AFLOW ``auid`` (with or without the ``aflow:`` prefix).

    Returns
    -------
    OptimadeStructure
        The validated structure, with space group and BAWL fingerprint computed.
    """
    # AFLOW is not uniformly PBE: some entries (e.g. in the LIB catalogs) were
    # computed with LDA pseudopotentials. The Functional enum cannot represent
    # those, so refuse to label them PBE; the transformer will skip the row.
    dft_type = attributes.get("dft_type")
    dft_types = dft_type if isinstance(dft_type, list) else [dft_type]
    if not dft_types or any(t != "PAW_PBE" for t in dft_types):
        raise ValueError("Explicit nonempty PAW_PBE dft_type is required")

    structure = build_structure_from_aflux(attributes)
    optimade_fields = get_optimade_from_pymatgen(structure)

    auid = str(entry_id).replace("aflow:", "").strip()
    immutable_id = f"aflow-{auid}"

    last_modified = parse_aflowlib_date(attributes.get("aflowlib_date"))

    return OptimadeStructure(
        **optimade_fields,
        id=f"{immutable_id}-{Functional.PBE.value}",
        immutable_id=immutable_id,
        source="aflow",
        functional=Functional.PBE,
        last_modified=last_modified or datetime.now(UTC),
        # Conservative until AFLOW DFT settings (spin polarization, pseudopotentials)
        # are audited against the compatibility criteria used for MP/Alexandria/OQMD.
        cross_compatibility=False,
        # Source energy stays in the raw table. Supplying it here would trigger
        # shared MP corrections with unaudited AFLOW U/POTCAR assumptions.
        energy=None,
        compute_space_group=True,
        compute_bawl_hash=True,
    )
