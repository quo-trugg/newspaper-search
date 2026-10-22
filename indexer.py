from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from whoosh import index, scoring
from whoosh.fields import ID, STORED, TEXT, Schema
from whoosh.qparser import MultifieldParser, OrGroup


def build_schema() -> Schema:
    """Build and return the Whoosh index schema for news articles."""
    return Schema(
        url=ID(stored=True, unique=True),
        title=TEXT(stored=True, field_boost=2.0),
        first_20_words=TEXT(stored=True),
        published_date=STORED,
    )


def _normalize_record(raw: dict[str, Any]) -> dict[str, str] | None:
    """Normalize raw dictionary into canonical keys, truncating first_20_words if needed."""
    title = str(
        raw.get("title") or raw.get("post_title") or raw.get("headline") or ""
    ).strip()
    url = str(
        raw.get("link") or raw.get("url") or raw.get("post_url") or ""
    ).strip()
    published_date = str(
        raw.get("published_date")
        or raw.get("published")
        or raw.get("date")
        or raw.get("pub_date")
        or "N/A"
    ).strip()
    first_20_words = str(
        raw.get("first_20_words")
        or raw.get("content_20_words")
        or raw.get("snippet")
        or raw.get("description")
        or raw.get("content")
        or ""
    ).strip()

    if not title or not url:
        return None

    words = first_20_words.split()
    if len(words) > 20:
        first_20_words = " ".join(words[:20])

    return {
        "url": url,
        "title": title,
        "first_20_words": first_20_words,
        "published_date": published_date,
    }


def load_dataset(data_dir: str | Path = "data") -> list[dict[str, str]]:
    """Load and deduplicate records from JSON and CSV files in data_dir."""
    data_path = Path(data_dir)
    if not data_path.exists():
        return []

    seen_urls: set[str] = set()
    records: list[dict[str, str]] = []

    for file_path in sorted(data_path.glob("*")):
        suffix = file_path.suffix.lower()
        raw_items: list[dict[str, Any]] = []

        if suffix == ".json":
            with file_path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    raw_items = loaded
                elif isinstance(loaded, dict):
                    for val in loaded.values():
                        if isinstance(val, list):
                            raw_items.extend(val)
        elif suffix == ".csv":
            with file_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                raw_items = list(reader)

        for item in raw_items:
            if not isinstance(item, dict):
                continue
            norm = _normalize_record(item)
            if norm and norm["url"] not in seen_urls:
                seen_urls.add(norm["url"])
                records.append(norm)

    return records


def get_or_create_index(
    index_dir: str | Path = "indexdir",
    data_dir: str | Path = "data",
) -> index.Index:
    """Open existing Whoosh index if present on disk, or create and populate it once."""
    index_path = str(index_dir)

    if os.path.exists(index_path) and index.exists_in(index_path):
        return index.open_dir(index_path)

    os.makedirs(index_path, exist_ok=True)
    ix = index.create_in(index_path, build_schema())
    records = load_dataset(data_dir)

    writer = ix.writer()
    for doc in records:
        writer.update_document(
            url=doc["url"],
            title=doc["title"],
            first_20_words=doc["first_20_words"],
            published_date=doc["published_date"],
        )
    writer.commit()
    return ix


def search_documents(
    ix: index.Index,
    query_str: str,
    limit: int = 20,
) -> list[dict[str, str]]:
    """Search documents using BM25F ranking on title and first_20_words."""
    clean_query = query_str.strip()
    if not clean_query:
        return []

    parser = MultifieldParser(
        ["title", "first_20_words"],
        schema=ix.schema,
        group=OrGroup,
    )
    parsed_query = parser.parse(clean_query)

    results_list: list[dict[str, str]] = []
    with ix.searcher(weighting=scoring.BM25F()) as searcher:
        hits = searcher.search(parsed_query, limit=limit)
        for hit in hits:
            results_list.append(
                {
                    "title": hit.get("title", ""),
                    "url": hit.get("url", ""),
                    "first_20_words": hit.get("first_20_words", ""),
                    "published_date": hit.get("published_date", "N/A"),
                    "score": f"{hit.score:.3f}",
                }
            )
    return results_list
