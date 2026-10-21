# Copyright 2026 Entalpic
"""One pinned export, with separate snapshot and publication dates."""

import re

ARCHIVE_URL = "https://ndownloader.figshare.com/files/64391379"
ARCHIVE_MD5 = "c3179161ef0d029cf1fa70da463aac6e"
ARCHIVE_VERSION = "jarvis-dft-3d-figshare6815699-v11-file64391379"
SNAPSHOT_DATE = "2025-09-24"
PUBLISHED_DATE = "2026-05-09T07:44:20Z"


def make_receipt(archive_sha256):
    """Describe verified export bytes, not per-entry modification dates."""
    if not isinstance(archive_sha256, str) or not re.fullmatch(
        "[0-9a-f]{64}", archive_sha256
    ):
        raise ValueError("archive SHA256 required")
    return {
        "source": "jarvis_dft",
        "version": ARCHIVE_VERSION,
        "release": ARCHIVE_VERSION,
        "artifact_kind": "published",
        "figshare_article_id": 6815699,
        "figshare_version": 11,
        "file_id": 64391379,
        "archive_name": "jdft_3d-9-24-2025.json.zip",
        "snapshot_date": SNAPSHOT_DATE,
        "published_date": PUBLISHED_DATE,
        "metadata_url": "https://api.figshare.com/v2/articles/6815699/versions/11",
        "url": ARCHIVE_URL,
        "archive_md5": ARCHIVE_MD5,
        "archive_sha256": archive_sha256,
        "scope": "raw source values; property methods remain separate",
    }
