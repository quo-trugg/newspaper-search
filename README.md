# Newspaper Search Engine

A fast, text-based news search engine over **VnExpress** and **BaoMoi** datasets (`.json` and `.csv`) using [Whoosh](https://whoosh.readthedocs.io/en/latest/quickstart.html) for full-text indexing and BM25F ranking, and [Streamlit](https://streamlit.io/) for the interactive web user interface.

## Features

- **Single-Time Idempotent Indexing**:
  - Checks if `indexdir/` already contains a valid Whoosh index before reading any files.
  - In `app.py`, index loading is cached with `@st.cache_resource`, ensuring that Streamlit never re-indexes on widget interactions or page reruns.
- **Automated Crawling Loop (15-Minute Revisit)**:
  - Continuously checks `https://vnexpress.net` (via breaking news RSS feeds) and `https://baomoi.com` (via latest article listings) every **15 minutes**.
  - **Deduplication**: Strictly skips any article already present in `data/` or `indexdir/`.
  - **Limit**: Crawls at most **50 new posts per website** per revisit cycle.
  - **Real-Time Indexing**: Immediately indexes newly discovered articles into Whoosh so they appear in search results without server restarts.
  - **Persistent Storage**: Saves newly crawled articles as UTF-8 JSON files in `data/`.
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
├── crawler.py                # 15-minute crawling loop for VnExpress & BaoMoi
├── app.py                    # Streamlit web search interface with crawler controls
├── data/                     # Source and newly crawled JSON/CSV datasets
│   ├── baomoi_2026-10-20_2026-10-22.csv
│   ├── baomoi_2026-10-20_2026-10-22.json
│   ├── vnexpress_last_week.csv
│   ├── vnexpress_last_week.json
│   └── crawled_articles.json
├── indexdir/                 # Persistent Whoosh index directory
└── tests/
    ├── test_search.py        # Automated unit and idempotency verification tests
    └── test_crawler.py       # Crawler deduplication, limit, and loop tests
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

## Running the Crawling Loop

You can run the crawler either independently via the CLI or directly from the Streamlit UI.

### Option A: Standalone CLI Loop (Every 15 Minutes)

Run the continuous crawling loop (revisits every 15 minutes, maximum 50 new posts per website):

```bash
python crawler.py
```

Options:
- `--interval <seconds>`: Revisit interval (default: `900` seconds / 15 minutes).
- `--max-posts <number>`: Maximum new posts per site per revisit (default: `50`).
- `--once`: Run a single revisit cycle immediately, index new posts, and exit.

Example (Single run):
```bash
python crawler.py --once
```

### Option B: From the Streamlit Web Application

The Streamlit sidebar includes:
- **⚡ Crawl New Posts Now**: Trigger an on-demand revisit immediately.
- **Auto-Revisit toggle**: Start/stop the 15-minute background crawling loop directly inside the web app.
- **Real-time Status**: Displays total indexed articles and statistics of the latest revisit.

## Running the Web Application

Start the Streamlit application:

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser. Enter keywords (e.g., `AI`, `công nghệ`, `kinh tế`, `thể thao`) to view ranked search results.

## Running Tests

Run the full automated test suite using `pytest`:

```bash
pytest -q
```
