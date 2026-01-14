# Copyright 2025 Entalpic
import functools
from datetime import datetime
from typing import Any, Optional, Type, List, Dict

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
from lematerial_fetcher.utils.config import TransformerConfig
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
        print('INside the transform_row function.')
        # 1. Extract the JSON blob
        if isinstance(raw_structure, dict):
            print('Raw structure is a dictionary.')
            data = raw_structure.get("data", {})
        else:
            print('Raw structure is not a dictionary.')
            attributes = getattr(raw_structure, "attributes", {})
            data = attributes.get("data", attributes)

        if not data:
            print('No data found.')
            return []

        auid = data.get("auid")
        if not auid:
            print('no AUID found.')
            return []

        try:
            # 2. Build Pymatgen Structure (The complex part)
            structure = self._build_structure(data)
            if not structure:
                logger.warning(f"Could not build structure for {auid} (missing geometry/species)")
                return []

            # 3. Extract Properties
            # Try to get formation enthalpy first, fallback to raw enthalpy per atom
            enthalpy_atom = data.get("enthalpy_formation_atom") or data.get("enthalpy_atom")
            enthalpy_cell = data.get("enthalpy_cell") 
            
            # Safely cast to float
            energy_pa = float(enthalpy_atom) if enthalpy_atom is not None else None
            energy_total = float(enthalpy_cell) if enthalpy_cell is not None else None
            
            # If we only have per-atom, calculate total
            if energy_total is None and energy_pa is not None:
                energy_total = energy_pa * structure.num_sites

            # 4. Create Optimade Structure
            optimade_keys = get_optimade_from_pymatgen(structure)
            

            # Determine Functional
            dft_raw = data.get("dft_type", ["Unknown"])
            dft_str = str(dft_raw[0]) if isinstance(dft_raw, list) and dft_raw else str(dft_raw)
            # Normalize to uppercase for easier matching (e.g. "PAW_PBE" -> "PAW_PBE")
            dft_str_upper = dft_str.upper()

            functional = None 
            
            # We want PAW_PBE and PAW_PBE_KIN:SCAN
            if "PBE" in dft_str_upper:
                # Watch out for "False Friends"
                if "SCAN" in dft_str_upper:
                    # e.g., "PAW_PBE:SCAN" -> This is SCAN, skip it (or map to Functional.SCAN if desired)
                    if dft_str_upper == "PAW_PBE_KIN:SCAN":
                        functional = Functional.SCAN
                    else:
                        logger.debug(f"Skipping {auid}: Unsupported functional '{dft_str}'")
                        return []
                elif  "KIN" in dft_str_upper:
                    logger.debug(f"Skipping {auid}: Unsupported functional '{dft_str}'")
                    return []
                elif "RPBE" in dft_str_upper:
                    # "PAW_RPBE" -> distinct functional, skip
                    logger.debug(f"Skipping {auid}: Unsupported functional '{dft_str}'")
                    return []
                else:
                    # Matches "PAW_PBE"
                    functional = Functional.PBE
            
            if functional is None:
                logger.debug(f"Skipping {auid}: No functional found for '{dft_str}'")
                return []
            
            
            if functional is None:
                # Optional: Log a warning if you want to track how many you are losing
                logger.debug(f"Skipping {auid}: Unsupported functional '{dft_str}'")
                return []
            
            # Extract band gap
            band_gap = data.get("Egap")

            print('Try to build the optimade structure.')
            # Build the object
            optimade_structure = OptimadeStructure(
                id=f"aflow-{auid}",
                source="aflow",
                immutable_id=f"aflow-{auid}",
                last_modified=datetime.now().isoformat(),
                
                # Structure
                **optimade_keys,
                # species_at_sites=[str(s) for s in structure.species],
                # cartesian_site_positions=structure.cart_coords.tolist(),
                
                # Properties
                energy=energy_total,
                functional=functional,
                band_gap_indirect=float(band_gap) if band_gap else None,
                
                # Metadata
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
        Requires: 'geometry' (lattice params), 'positions_fractional', 'species', 'composition'.
        """
        # A. Create Lattice
        # geometry = [a, b, c, alpha, beta, gamma]
        geo_params = data.get("geometry")
        if not geo_params or len(geo_params) != 6:
            return None
        
        try:
            lattice = Lattice.from_parameters(*geo_params)
        except Exception:
            return None

        # B. Get Coordinates (Prefer Fractional)
        coords = data.get("positions_fractional")
        coords_are_cartesian = False
        
        if not coords:
            # Fallback to cartesian if fractional missing
            coords = data.get("positions_cartesian")
            coords_are_cartesian = True
            
        if not coords:
            return None

        # C. Expand Species List
        # AFLOW data: species=['Ag', 'O'], composition=[2, 4]
        # Pymatgen needs: ['Ag', 'Ag', 'O', 'O', 'O', 'O']
        species_types = data.get("species")
        composition = data.get("composition") # Counts
        
        if not species_types or not composition or len(species_types) != len(composition):
            return None
            
        expanded_species = []
        for sp, count in zip(species_types, composition):
            # count might be a float in the JSON, cast to int
            expanded_species.extend([sp] * int(count))
            
        # Validation
        if len(expanded_species) != len(coords):
            # Mismatch between atoms and coordinates -> invalid structure
            return None

        return Structure(
            lattice=lattice, 
            species=expanded_species, 
            coords=coords, 
            coords_are_cartesian=coords_are_cartesian
        )
