# Copyright 2025 Entalpic
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from multiprocessing import Manager
from typing import Any

from lematerial_fetcher.database.postgres import StructuresDatabase
from lematerial_fetcher.fetch import BaseFetcher, BatchInfo, ItemsInfo
from lematerial_fetcher.fetcher.aflow.utils import (
    build_aflux_query,
    parse_aflowlib_date,
)
from lematerial_fetcher.models.models import RawStructure
from lematerial_fetcher.utils.config import FetcherConfig, load_fetcher_config
from lematerial_fetcher.utils.io import create_session
from lematerial_fetcher.utils.logging import logger


class AflowFetcher(BaseFetcher):
    """Fetcher for the AFLOW database, through the AFLUX search API.

    Note: AFLOW also exposes an OPTIMADE endpoint, but it is unreliable at the time
    of writing (persistent HTTP 500), so we query AFLUX directly and request the
    geometry properties needed to rebuild each unit cell.
    """

    def __init__(self, config: FetcherConfig = None, debug: bool = False):
        """Initialize the fetcher."""
        super().__init__(config or load_fetcher_config(), debug)
        self.manager = Manager()
        self.manager_dict = self.manager.dict()
        self.manager_dict["occurred"] = False

    def setup_resources(self) -> None:
        """Set up necessary resources."""
        logger.info("Setting up AFLOW fetcher resources")
        self.setup_database()

    def get_items_to_process(self) -> ItemsInfo:
        """Get information about batches to process.

        AFLUX does not expose a cheap total count, so we use pagination mode:
        batches are generated dynamically during processing and we stop as soon
        as a page comes back empty.
        """
        return ItemsInfo(start_offset=self.config.page_offset)

    def process_items(self, items_info: ItemsInfo) -> None:
        """Check every submitted page before recording a completed fetch.

        Read a bounded group of pages at a time. Worker failures and future
        exceptions both stop the fetch, even when another page has reached EOF.
        """
        if items_info.items is not None:
            raise ValueError("AFLOW requires pagination")
        workers = 1 if self.debug else self.config.num_workers
        if workers < 1 or self.config.page_limit < 1 or items_info.start_offset < 0:
            raise ValueError(
                "AFLOW requires positive workers/page size and a nonnegative offset"
            )
        self.manager_dict["failed"] = False
        self.manager_dict["occurred"] = False
        pool = None if self.debug else ProcessPoolExecutor(max_workers=workers)
        offset = items_info.start_offset
        try:
            while True:
                batches = [
                    BatchInfo(
                        offset=offset + i * self.config.page_limit,
                        limit=self.config.page_limit,
                    )
                    for i in range(workers)
                    if items_info.total_count is None
                    or offset + i * self.config.page_limit < items_info.total_count
                ]
                if not batches:
                    return
                if pool is None:
                    results = [
                        self._process_batch(batch, self.config, self.manager_dict)
                        for batch in batches
                    ]
                else:
                    futures = [
                        pool.submit(
                            self.__class__._process_batch,
                            batch,
                            self.config,
                            self.manager_dict,
                            worker_id=i,
                        )
                        for i, batch in enumerate(batches)
                    ]
                    # Do not ignore exceptions from pages submitted before EOF.
                    results = [future.result() for future in futures]
                if self.manager_dict.get("failed", False):
                    raise RuntimeError(
                        "AFLOW fetch failed; no completed version was recorded"
                    )
                if any(type(result) is not bool for result in results):
                    raise RuntimeError("AFLOW worker did not report page completion")
                if not all(results):
                    return
                offset += len(batches) * self.config.page_limit
        finally:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)

    @staticmethod
    def _process_batch(
        batch: Any, config: FetcherConfig, manager_dict: dict, worker_id: int = 0
    ) -> bool:
        """Read one page. Empty pages end the fetch; errors also set a failure flag.

        Workers report errors through a shared flag. The parent also checks every
        future, including failures that happen before a worker can set that flag.
        """
        db = None
        session = None
        more_data = False
        try:
            db = StructuresDatabase(config.db_conn_str, config.table_name)
            session = create_session()
            page = batch.offset // batch.limit + 1
            url = build_aflux_query(config.base_url, page=page, per_page=batch.limit)
            response = session.get(url, timeout=120)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise TypeError("AFLOW returned an invalid page; expected a list")
            if data:
                structures = []
                for entry in data:
                    if not isinstance(entry, dict):
                        raise TypeError("AFLOW page contains a non-object entry")
                    auid = str(entry.get("auid", "")).strip()
                    if not auid:
                        continue
                    last_modified = parse_aflowlib_date(entry.get("aflowlib_date"))
                    structures.append(
                        RawStructure(
                            id=auid,
                            type="aflow-structure",
                            attributes=entry,
                            last_modified=(
                                last_modified.strftime("%Y-%m-%d")
                                if last_modified
                                else None
                            ),
                        )
                    )
                if structures:
                    db.batch_insert_data(structures)
                more_data = True
        except Exception as error:
            if manager_dict is None:
                raise
            manager_dict["failed"] = True
            manager_dict["occurred"] = True
            logger.error(f"AFLOW page at offset {batch.offset} failed: {error}")
        finally:
            for resource in (session, db):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception as error:
                        more_data = False
                        if manager_dict is None:
                            raise
                        manager_dict["failed"] = True
                        manager_dict["occurred"] = True
                        logger.error(f"AFLOW resource cleanup failed: {error}")
        return more_data

    def cleanup_resources(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up AFLOW fetcher resources")

    def get_new_version(self) -> str:
        """Get a new version string."""
        return datetime.now(UTC).isoformat()
