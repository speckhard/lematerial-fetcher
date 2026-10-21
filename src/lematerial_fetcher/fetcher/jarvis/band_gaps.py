# Copyright 2026 Entalpic
"""Extract separate JARVIS gap observations, not certified training labels.

No MP energy corrections, formula matching, missing-gap imputation or inferred
spin/U/SOC/convergence evidence. Archive verification belongs to acquisition.
"""

import copy
import hashlib
import json
import math
import re

from lematerial_fetcher.fetcher.jarvis.release import make_receipt

ELEMENTS = {
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
    "Fr",
    "Ra",
    "Ac",
    "Th",
    "Pa",
    "U",
    "Np",
    "Pu",
    "Am",
    "Cm",
    "Bk",
    "Cf",
    "Es",
    "Fm",
    "Md",
    "No",
    "Lr",
    "Rf",
    "Db",
    "Sg",
    "Bh",
    "Hs",
    "Mt",
    "Ds",
    "Rg",
    "Cn",
    "Nh",
    "Fl",
    "Mc",
    "Lv",
    "Ts",
    "Og",
}


def record_hash(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _geometry(atoms):
    if not isinstance(atoms, dict) or type(atoms.get("cartesian")) is not bool:
        raise ValueError("explicit atoms coordinate basis required")
    lattice, coords, elements = (
        atoms.get(k) for k in ("lattice_mat", "coords", "elements")
    )
    if not isinstance(lattice, list) or len(lattice) != 3:
        raise ValueError("3x3 lattice required")
    if (
        not isinstance(elements, list)
        or not 1 <= len(elements) <= 2048
        or any(e not in ELEMENTS for e in elements if isinstance(e, str))
        or any(not isinstance(e, str) for e in elements)
    ):
        raise ValueError("bounded valid element list required")
    if not isinstance(coords, list) or len(coords) != len(elements):
        raise ValueError("site count mismatch")
    for vector in lattice + coords:
        if (
            not isinstance(vector, list)
            or len(vector) != 3
            or not all(_finite(v) for v in vector)
        ):
            raise ValueError("finite three-component geometry required")
    a, b, c = lattice
    det = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if not _finite(det) or abs(det) < 1e-12:
        raise ValueError("nonsingular lattice required")
    return copy.deepcopy(atoms)


def extract_band_gaps(raw, receipt):
    """Return two method-specific observations, including missing/invalid masks.

    Receipt binds the full raw row and declared archive. It is not independent
    proof that a gap calculation used the archive's associated structure.
    """
    if not isinstance(raw, dict) or not re.fullmatch(
        r"JVASP-[1-9][0-9]*", str(raw.get("jid", ""))
    ):
        raise ValueError("JARVIS identity required")
    if receipt.get("source") != "jarvis_dft":
        raise ValueError("source mismatch")
    kind = receipt.get("artifact_kind")
    if kind not in ("published", "synthetic_fixture"):
        raise ValueError("explicit artifact kind required")
    for key in ("archive_sha256", "raw_record_sha256"):
        if not isinstance(receipt.get(key), str) or not re.fullmatch(
            "[0-9a-f]{64}", receipt[key]
        ):
            raise ValueError("SHA256 required")
    if not isinstance(receipt.get("release"), str) or not receipt["release"].strip():
        raise ValueError("release required")
    if kind == "published":
        expected = make_receipt(receipt["archive_sha256"])
        for key in expected:
            if key != "scope" and receipt.get(key) != expected[key]:
                raise ValueError(
                    "published receipt does not match pinned export: " + key
                )
    raw_hash = record_hash(raw)
    if raw_hash != receipt["raw_record_sha256"]:
        raise ValueError("raw record binding mismatch")
    atoms = _geometry(raw.get("atoms"))
    geometry = {k: atoms[k] for k in ("lattice_mat", "elements", "coords", "cartesian")}
    labels = []
    for field, method in [("optb88vdw_bandgap", "optB88vdW"), ("mbj_bandgap", "TBmBJ")]:
        value = raw.get(field)
        missing = value is None or (
            isinstance(value, str) and value.strip().lower() in ("", "na")
        )
        valid = _finite(value) and value >= 0
        reasons = [] if valid else ["missing_gap" if missing else "invalid_gap"]
        labels.append(
            {
                "source": "jarvis_dft",
                "release": receipt["release"],
                "artifact_kind": kind,
                "record_id": raw["jid"],
                "calculation_id": receipt["release"] + ":" + raw["jid"] + ":" + field,
                "target": "band_gap",
                "unit": "eV",
                "raw_field": field,
                "raw_value": copy.deepcopy(value),
                "value": value if valid else None,
                "label_mask": valid,
                "reasons": reasons,
                "atoms": copy.deepcopy(atoms),
                "geometry_sha256": record_hash(geometry),
                "raw_record_sha256": raw_hash,
                "archive_sha256": receipt["archive_sha256"],
                "source_receipt": {
                    key: copy.deepcopy(receipt[key])
                    for key in (
                        "figshare_article_id",
                        "figshare_version",
                        "file_id",
                        "archive_name",
                        "snapshot_date",
                        "published_date",
                        "metadata_url",
                        "url",
                        "archive_md5",
                    )
                    if key in receipt
                },
                "protocol": {
                    "functional": method,
                    "gap_definition": "reported electronic band gap",
                    "geometry_method": "source-associated structure; calculation binding unaudited",
                    "soc": None,
                    "uses_u": None,
                },
                "evidence": {
                    "nonmagnetic": None,
                    "uses_u": None,
                    "soc": None,
                    "converged": None,
                    "calculation_geometry_verified": False,
                },
                "training_eligible": False,
            }
        )
    return labels


def extract_stored_band_gaps(attributes):
    """Read stored raw attributes without hashing the added ingestion metadata.

    This binds observations to the current raw row; it does not independently
    prove archive membership or an electronic calculation's reference geometry.
    """
    if not isinstance(attributes, dict):
        raise TypeError("stored JARVIS attributes must be an object")
    if "_lematerial_ingestion" not in attributes:
        raise ValueError("stored JARVIS ingestion receipt required")
    if not isinstance(attributes["_lematerial_ingestion"], dict):
        raise TypeError("stored JARVIS receipt must be an object")
    raw = {
        key: copy.deepcopy(value)
        for key, value in attributes.items()
        if key != "_lematerial_ingestion"
    }
    receipt = copy.deepcopy(attributes["_lematerial_ingestion"])
    digest = record_hash(raw)
    if receipt.get("raw_record_sha256") not in (None, digest):
        raise ValueError("stored raw record hash conflicts with receipt")
    receipt["raw_record_sha256"] = digest
    return extract_band_gaps(raw, receipt)
