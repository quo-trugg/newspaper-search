---
name: whoosh-streamlit-search
description: Build, index, and verify a Whoosh full-text search engine with a Streamlit GUI over JSON and CSV news datasets. Use when implementing or updating the Whoosh schema, dataset ingestion for VnExpress and BaoMoi, single-time indexing with st.cache_resource, or the Streamlit search interface.
---
# Whoosh Streamlit Search Engine

Implement and maintain a text-based news search engine using Whoosh and Streamlit for VnExpress and BaoMoi datasets (`.json` and `.csv`), guaranteeing that indexing runs only once and never repeats on Streamlit script reruns.

## When to Use

- Initializing or updating the Whoosh schema and indexer (`indexer.py`) for news articles.
- Ingesting and normalizing `.json` and `.csv` datasets containing post title, link, published date, and first 20 words.
- Building or modifying the Streamlit search GUI (`app.py`) with `@st.cache_resource`.
- Writing or running verification tests to prove the dataset is indexed only once.

## Decision Tree

- **Does `indexdir/` already contain a valid Whoosh index (`whoosh.index.exists_in(index_dir)`)?**

  - **Yes**: Call `whoosh.index.open_dir(index_dir)` immediately. Do not read `.csv` or `.json` files again.
  - **No**: Create `indexdir/`, initialize the schema with `whoosh.index.create_in(index_dir, schema)`, ingest the `.csv` and `.json` files once in a single batch writer (`ix.writer()`), and commit.

- **Did the schema fields change during development?**

  - **Yes**: Delete `indexdir/` once (`shutil.rmtree("indexdir")`) and let `get_or_create_index()` rebuild it on the next startup.

## Steps

### Step 1: Inspect and Normalize JSON and CSV Datasets

1. Scan the `data/` directory (or workspace root) for `.json` and `.csv` files from VnExpress and BaoMoi.
2. Read CSV files with `encoding="utf-8-sig"` and JSON files with `encoding="utf-8"`.
3. Normalize varying column or key names into four canonical fields (`title`, `url`, `published_date`, and `first_20_words`) and truncate the snippet to at most 20 words if raw descriptions are longer.

### Step 2: Implement Idempotent Indexing and Search in `indexer.py`

Create `indexer.py` with explicit disk-level index detection (`exists_in`) and `BM25F` multi-field ranking:

```python
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
    return Schema(
        url=ID(stored=True, unique=True),
        title=TEXT(stored=True, field_boost=2.0),
        first_20_words=TEXT(stored=True),
        published_date=STORED,
    )


def _normalize_record(raw: dict[str, Any]) -> dict[str, str] | None:
    title = str(
        raw.get("title") or raw.get("post_title") or raw.get("headline") or ""
    ).strip()
    url = str(
        raw.get("link") or raw.get("url") or raw.get("post_url") or ""
    ).strip()
    published_date = str(
        raw.get("published_date")
        or raw.get("date")
        or raw.get("pub_date")
        or "N/A"
    ).strip()
    first_20_words = str(
        raw.get("first_20_words")
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
```

### Step 3: Build the Cached Streamlit Interface in `app.py`

Use `@st.cache_resource` so Streamlit caches the `Whoosh` index object across script reruns:

```python
import streamlit as st
from indexer import get_or_create_index, search_documents

st.set_page_config(
    page_title="VnExpress & BaoMoi Search Engine",
    page_icon="🔍",
    layout="centered",
)


@st.cache_resource(show_spinner="Loading search index...")
def load_cached_index():
    return get_or_create_index(index_dir="indexdir", data_dir="data")


def main() -> None:
    st.title("VnExpress & BaoMoi Search Engine")
    st.caption("Full-text search powered by Whoosh and Streamlit")

    ix = load_cached_index()
    query = st.text_input(
        "Search articles by keywords:",
        placeholder="Enter keywords (e.g., kinh te, cong nghe, giao duc)...",
    )

    if query.strip():
        results = search_documents(ix, query, limit=25)
        st.write(f"Found **{len(results)}** matching document(s) ranked by relevance:")

        for rank, item in enumerate(results, start=1):
            with st.container(border=True):
                st.markdown(f"#### {rank}. [{item['title']}]({item['url']})")
                st.markdown(f"**URL:** {item['url']}")
                st.markdown(f"**First 20 words:** {item['first_20_words']}")
                st.caption(f"Published date: {item['published_date']}")


if __name__ == "__main__":
    main()
```

### Step 4: Create `requirements.txt`, `README.md`, and Unit Tests

1. Create `requirements.txt` with `Whoosh>=2.7.4`, `streamlit>=1.32.0`, `pandas>=2.0.0`, and `pytest>=8.0.0`.
2. Create `tests/test_search.py` to verify that calling `get_or_create_index()` a second time opens the existing index without re-indexing (`load_dataset` is called only once) and returns ranked results with all four required fields (`title`, `url`, `first_20_words`, `published_date`).
3. Run `pytest -q` to validate before completing the task.

## Gotchas

- **Never use `@st.cache_data` for Whoosh index objects**: Whoosh `FileIndex` objects manage file locks and cannot be pickled safely by `@st.cache_data`. Always use `@st.cache_resource`.
- **Do not return raw Whoosh `Hit` objects outside `with ix.searcher()`**: Once the `with` block exits, the searcher closes and accessing `hit["title"]` raises `ReaderClosed`. Always copy fields into plain dictionaries inside the `with` block.
- **CSV BOM headers**: CSV files exported on Windows often start with a UTF-8 BOM (`\ufeff`), which turns the first column header into `\ufefftitle` if opened with `utf-8`. Always open CSV files with `encoding="utf-8-sig"`.
