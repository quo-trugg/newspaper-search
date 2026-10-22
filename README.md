# Newspaper Search Engine

A fast, text-based news search engine over **VnExpress** and **BaoMoi** datasets (`.json` and `.csv`) using [Whoosh](https://whoosh.readthedocs.io/en/latest/quickstart.html) for full-text indexing and BM25F ranking, and [Streamlit](https://streamlit.io/) for the interactive web user interface.

## Features

- **Single-Time Idempotent Indexing**:
  - Checks if `indexdir/` already contains a valid Whoosh index before reading any files.
  - In `app.py`, index loading is cached with `@st.cache_resource`, ensuring that Streamlit never re-indexes on widget interactions or page reruns.
- **UTF-8 Support for Vietnamese Text**:
  - Ingests CSV files using `utf-8-sig` (handling Windows BOM) and JSON files using `utf-8`.
- **Field Normalization & Deduplication**:
  - Canonical mapping for `title`, `url` (link), `published_date`, and `first_20_words`.
  - Truncates opening snippet to at most 20 words.
  - Discards blank or fragment entries (`#box_comment_vne`) and deduplicates documents by `url`.
- **Relevance Ranking & Display**:
  - `BM25F` scoring across `title` (with a 2.0 boost) and `first_20_words`.
  - Every search result displays all 4 required fields: `title`, `url` (clickable link), `first_20_words`, and `published_date`.

## Repository Structure

```text
.
├── AGENTS.md                 # Agent and workspace rules
├── README.md                 # Project setup and usage instructions
├── requirements.txt          # Python dependencies
├── pytest.ini                # Pytest configuration
├── indexer.py                # Schema definition, data loading, indexing, and search logic
├── app.py                    # Streamlit web search interface
├── data/                     # Source JSON and CSV datasets (VnExpress, BaoMoi)
│   ├── baomoi_2026-10-20_2026-10-22.csv
│   ├── baomoi_2026-10-20_2026-10-22.json
│   ├── vnexpress_last_week.csv
│   └── vnexpress_last_week.json
├── indexdir/                 # Persistent Whoosh index directory (generated on first run)
└── tests/
    └── test_search.py        # Automated unit and idempotency verification tests
```

## Installation & Setup

1. **Clone or open the repository**:
   ```bash
   cd TextSearchSystemOct23
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Web Application

Start the Streamlit application:

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser. Enter keywords (e.g., `AI`, `công nghệ`, `kinh tế`, `thể thao`) to view ranked search results.

## Running Tests

Run the test suite using `pytest`:

```bash
pytest -q
```
