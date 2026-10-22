# AGENTS.md - VnExpress & BaoMoi Whoosh Search Engine

## Project Overview

This repository implements a fast, text-based news search engine over **VnExpress** and **BaoMoi** datasets (`.json` and `.csv`) using [Whoosh](https://whoosh.readthedocs.io/en/latest/quickstart.html) for full-text indexing and ranking and [Streamlit](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_resource) for the graphical user interface (GUI).

Each article record contains four core attributes:

- **Title** (`title`): Post headline.
- **Link** (`url` / `link`): Canonical URL to the original article.
- **Published Date** (`published_date`): Publication timestamp or date string.
- **First 20 Words** (`first_20_words` / `content`): Opening 20-word snippet of the article.

## Repository Structure

```text
.
├── AGENTS.md                                          # Workspace rules auto-loaded by Antigravity CLI
├── .agents/
│   └── skills/
│       └── whoosh-streamlit-search/
│           └── SKILL.md                               # Reusable skill (/whoosh-streamlit-search)
├── data/                                              # Input JSON and CSV files (VnExpress, BaoMoi)
├── indexdir/                                          # Persistent Whoosh index directory (built once)
├── indexer.py                                         # Data loading, schema definition, and Whoosh indexing
├── app.py                                             # Main Streamlit GUI entry point
├── tests/
│   └── test_search.py                                 # Verification tests for single-index & search ranking
├── requirements.txt                                   # Python dependencies (Whoosh, streamlit, pandas, pytest)
└── README.md                                          # Setup and execution instructions
```

## Non-Negotiable Architecture Rules

1. **Index the Dataset Only Once (Critical)**:
   - Streamlit re-runs the entire Python script on every widget interaction. Never call `index.create_in()` or re-ingest CSV/JSON files unconditionally in `app.py`.
   - **Disk layer (`indexer.py`)**: Always check `os.path.exists(index_dir) and whoosh.index.exists_in(index_dir)` ([Whoosh Indexing Docs](https://whoosh.readthedocs.io/en/latest/indexing.html)) first. If true, open and return `whoosh.index.open_dir(index_dir)`. Only build the index with `whoosh.index.create_in(index_dir, schema)` when the index does not exist on disk.
   - **Memory layer (`app.py`)**: Always decorate the index loader function with `@st.cache_resource` ([Streamlit Caching Docs](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_resource)) so Streamlit keeps a single cached `FileIndex` reference across all user interactions and reruns.

2. **UTF-8 Encoding for Vietnamese Text**:
   - Always read `.json` files with `encoding="utf-8"` and `.csv` files with `encoding="utf-8-sig"` so Vietnamese diacritics in VnExpress and BaoMoi posts never corrupt.

3. **Resilient Field Mapping & Deduplication**:
   - Map common source column variations into four canonical fields (`title`, `url`, `published_date`, `first_20_words`) and deduplicate documents by `url` before writing to Whoosh.

4. **Relevance Ranking & Required Display Fields**:
   - Parse user keyword queries using `whoosh.qparser.MultifieldParser(["title", "first_20_words"], schema=ix.schema, group=whoosh.qparser.OrGroup)` ([Whoosh Query Parsing Docs](https://whoosh.readthedocs.io/en/latest/parsing.html)) and score with `whoosh.scoring.BM25F()` so results are ordered from most to least relevant.
   - Every search result rendered in the Streamlit UI must display all four required fields: `title`, `url` (clickable link), `first_20_words`, and `published_date`.

5. **Required Project Files**:
   - Maintain a clean `requirements.txt` listing all required packages (`Whoosh`, `streamlit`, `pandas`, `pytest`).
   - Keep `app.py` as the primary runnable entry point and document `streamlit run app.py` in `README.md`.

## Coding Conventions

- Target Python 3.10+ with type annotations on all public functions.
- Always open Whoosh searchers using a context manager (`with ix.searcher() as searcher:`) and convert hits to plain Python `dict` objects before exiting the `with` block.
- Never commit `indexdir/`, `.venv/`, or `__pycache__/` to version control.

## Verification Loop Commands

Before marking any implementation or edit complete, execute the following verification steps:

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run automated tests (verifies single-time indexing and search ranking)**:
   ```bash
   pytest -q
   ```

3. **Smoke-test the Streamlit app headlessly**:
   ```bash
   streamlit run app.py --server.headless true
   ```
