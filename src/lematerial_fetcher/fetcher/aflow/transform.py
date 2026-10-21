# Copyright 2025 Entalpic
from typing import Any

from lematerial_fetcher.database.postgres import StructuresDatabase
from lematerial_fetcher.fetcher.aflow.utils import transform_aflux_entry
from lematerial_fetcher.models.models import RawStructure
from lematerial_fetcher.models.optimade import OptimadeStructure
from lematerial_fetcher.transform import BaseTransformer
from lematerial_fetcher.utils.logging import logger


class AflowTransformer(BaseTransformer):
    """
    AFLOW transformer implementation.
    Transforms raw AFLUX entries into OptimadeStructures.
    """

    def transform_row(
        self,
        raw_structure: RawStructure | dict[str, Any],
        source_db: StructuresDatabase | None = None,
        task_table_name: str | None = None,
    ) -> list[OptimadeStructure]:
        """
        Transform a raw AFLOW structure into OptimadeStructures.

        Parameters
        ----------
        raw_structure : RawStructure
            RawStructure object from the dumped database
        source_db : Optional[StructuresDatabase]
            Source database connection (unused for AFLOW)
        task_table_name : Optional[str]
            Task table name (unused for AFLOW)

        Returns
        -------
        list[OptimadeStructure]
            The transformed OptimadeStructure objects.
            If the list is empty, nothing from the structure is included in the database.
        """
        try:
            optimade_structure = transform_aflux_entry(
                raw_structure.attributes, raw_structure.id
            )
        except Exception as e:  # noqa: BLE001 -- Keep invalid rows in raw storage and skip their transform.
            logger.warning(f"Error transforming structure {raw_structure.id}: {e}")
            return []

        return [optimade_structure]
