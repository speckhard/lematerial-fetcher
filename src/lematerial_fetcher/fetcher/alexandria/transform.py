# Copyright 2025 Entalpic
"""Transform raw API rows from the fetch.py script into optimade structures."""
from datetime import datetime
from typing import Any, Optional, Dict, List

from pymatgen.core import Structure, Lattice

from lematerial_fetcher.database.postgres import (
    OptimadeDatabase,
    StructuresDatabase,
)
from lematerial_fetcher.models.models import RawStructure
from lematerial_fetcher.models.optimade import (
    OptimadeStructure, 
    Functional, 
)
from lematerial_fetcher.transform import BaseTransformer
from lematerial_fetcher.utils.logging import logger
from lematerial_fetcher.utils.structure import get_optimade_from_pymatgen

class AflowTransformer(BaseTransformer[OptimadeDatabase, OptimadeStructure]):
    """
    AFLOW transformer implementation.
    Transforms raw AFLOW JSON data (from Postgres) into OptimadeStructures.
    """

    def transform_row(
        self,
        raw_structure: RawStructure | dict[str, Any],
        source_db: Optional[StructuresDatabase] = None,
        task_table_name: Optional[str] = None,
    ) -> list[OptimadeStructure]:
        
        # 1. Extract the JSON blob safely
        if isinstance(raw_structure, dict):
            data = raw_structure.get("data", {})
        else:
            data = getattr(raw_structure, "data", {})

        if not data:
            return []

        auid = data.get("auid")
        if not auid:
            return []

        try:
            # 2. Build Pymatgen Structure
            structure = self._build_structure(data)
            if not structure:
                logger.warning(f"Skipping {auid}: Invalid structure construction (missing geometry or species mismatch).")
                return []

            # 3. Extract Properties
            # Energy: AFLOW gives eV/cell. We also check per-atom as backup.
            enthalpy_atom = data.get("enthalpy_formation_atom") or data.get("enthalpy_atom")
            enthalpy_cell = data.get("energy_cell") 
            
            energy_total = None
            if enthalpy_cell is not None:
                energy_total = float(enthalpy_cell)
            elif enthalpy_atom is not None:
                # Fallback: calculate total if only per-atom is available
                energy_total = float(enthalpy_atom) * structure.num_sites

            # Functional (PBE, LDA, SCAN, etc.)
            dft_raw = data.get("dft_type", ["Unknown"])
            # dft_type is often a list ["PAW_PBE"], but sometimes just a string.
            dft_str = str(dft_raw[0]) if isinstance(dft_raw, list) and dft_raw else str(dft_raw)
            dft_str = dft_str.upper()

            functional = Functional.UNKNOWN
            if "PBE" in dft_str:
                functional = Functional.PBE
            elif "LDA" in dft_str:
                functional = Functional.LDA
            elif "SCAN" in dft_str:
                functional = Functional.SCAN
            
            # Band Gap
            band_gap_raw = data.get("Egap")
            band_gap = float(band_gap_raw) if band_gap_raw is not None else None
            
            # 4. Create Optimade Structure
            # get_optimade_from_pymatgen handles: elements, nelements, lattice_vectors, etc.
            optimade_keys = get_optimade_from_pymatgen(structure)
            
            optimade_structure = OptimadeStructure(
                id=f"aflow-{auid}",
                source="aflow",
                immutable_id=f"aflow-{auid}",
                last_modified=datetime.now(), # Or parse data.get('aflowlib_date') if available
                
                # Structure Fields
                **optimade_keys,
                species_at_sites=[str(s) for s in structure.species],
                cartesian_site_positions=structure.cart_coords.tolist(),
                
                # Properties
                energy=energy_total,
                functional=functional,
                band_gap_indirect=band_gap,
                
                # Metadata / Calculations
                cross_compatibility=True, 
                compute_space_group=True,
                compute_bawl_hash=True
            )
            
            return [optimade_structure]

        except Exception as e:
            logger.warning(f"Failed to transform AFLOW entry {auid}: {e}")
            return []

    def _build_structure(self, data: Dict[str, Any]) -> Optional[Structure]:
        """
        Constructs a Structure from AFLOW's parameter lists.
        """
        # A. Create Lattice
        # geometry = [a, b, c, alpha, beta, gamma]
        geo_params = data.get("geometry")
        if not geo_params or not isinstance(geo_params, list) or len(geo_params) != 6:
            return None
        
        try:
            lattice = Lattice.from_parameters(*geo_params)
        except Exception:
            return None

        # B. Get Coordinates
        # Try fractional first (preferred for crystals), then cartesian
        coords = data.get("positions_fractional")
        coords_are_cartesian = False
        
        if not coords:
            coords = data.get("positions_cartesian")
            coords_are_cartesian = True
            
        if not coords or not isinstance(coords, list):
            return None

        # C. Expand Species List
        # AFLOW data: species=['Ag', 'O'], composition=[2, 4]
        # Pymatgen needs: ['Ag', 'Ag', 'O', 'O', 'O', 'O']
        species_types = data.get("species")
        composition = data.get("composition") 
        
        if not species_types or not composition or len(species_types) != len(composition):
            return None
            
        expanded_species = []
        for sp, count in zip(species_types, composition):
            try:
                # count might be 1 or 1.0 or "1"
                expanded_species.extend([sp] * int(float(count)))
            except ValueError:
                return None
            
        # Validation
        # The number of atoms must match the number of coordinate positions
        if len(expanded_species) != len(coords):
            return None

        return Structure(
            lattice=lattice, 
            species=expanded_species, 
            coords=coords, 
            coords_are_cartesian=coords_are_cartesian
        )
