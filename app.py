from __future__ import annotations

import threading
import time
from typing import Any

import streamlit as st

from crawler import (
    crawl_and_index_revisit,
    get_crawler_status,
    run_crawler_loop,
)
from image_search import (
    get_or_create_image_index,
    search_images,
)
from indexer import get_or_create_index, search_documents

st.set_page_config(
    page_title="VnExpress & BaoMoi Search Engine",
    page_icon="🔍",
    layout="centered",
)


@st.cache_resource(show_spinner="Initializing article search index...")
def load_cached_index():
    """Load or initialize the Whoosh article search index once and cache the reference."""
    return get_or_create_index(index_dir="indexdir", data_dir="data")


@st.cache_resource(show_spinner="Initializing image search index...")
def load_cached_image_index():
    """Load or initialize the Whoosh image search index once and cache the reference."""
    return get_or_create_image_index(
        index_dir="image_indexdir",
        data_file="data/images_dataset.json",
    )


class CrawlerWorker:
    """Singleton background worker to manage the 15-minute crawling loop inside Streamlit."""

    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.is_running = False

    def start(self, interval_seconds: int = 900, max_per_site: int = 50) -> None:
        if self.is_running and self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.is_running = True
        self.thread = threading.Thread(
            target=self._run,
            args=(interval_seconds, max_per_site),
            daemon=True,
            name="CrawlerWorkerThread",
        )
        self.thread.start()

    def stop(self) -> None:
        if not self.is_running:
            return
        self.stop_event.set()
        self.is_running = False

    def _run(self, interval_seconds: int, max_per_site: int) -> None:
        try:
            run_crawler_loop(
                interval_seconds=interval_seconds,
                max_per_site=max_per_site,
                data_dir="data",
                index_dir="indexdir",
                stop_event=self.stop_event,
            )
        finally:
            self.is_running = False


@st.cache_resource
def get_crawler_worker() -> CrawlerWorker:
    """Return the cached singleton crawler worker instance."""
    return CrawlerWorker()


def render_sidebar(ix: Any, ix_image: Any) -> None:
    """Render sidebar controls and status for the 15-minute Crawling Loop."""
    worker = get_crawler_worker()
    st.sidebar.header("🔄 Crawling Loop")

    status_data = get_crawler_status(data_dir="data")
    total_docs = ix.doc_count()
    total_images = ix_image.doc_count()

    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.metric(label="Articles", value=f"{total_docs:,}")
    with col2:
        st.metric(label="Images", value=f"{total_images:,}")

    with st.sidebar.container(border=True):
        st.markdown("**Crawler Status**")
        worker_active = worker.is_running and worker.thread and worker.thread.is_alive()
        status_label = "🟢 Running (every 15 min)" if worker_active else "⚪ Idle"
        st.write(f"**State:** {status_label}")
        st.write(f"**Last Run:** {status_data.get('timestamp', 'Never')}")
        if status_data.get("timestamp"):
            st.caption(
                f"+{status_data.get('vnexpress_new', 0)} VnExpress, "
                f"+{status_data.get('baomoi_new', 0)} BaoMoi "
                f"({status_data.get('total_new', 0)} total new)"
            )

    # Action: Run immediate revisit
    if st.sidebar.button("⚡ Crawl New Posts Now", width="stretch"):
        with st.sidebar.status("Revisiting VnExpress & BaoMoi...", expanded=True) as status_box:
            st.write("Checking for new unindexed articles (max 50/site)...")
            res = crawl_and_index_revisit(
                index_dir="indexdir",
                data_dir="data",
                max_per_site=50,
            )
            # Refresh Whoosh index readers
            ix.refresh()
            ix_image.refresh()
            status_box.update(
                label=f"Done! +{res['total_new']} new posts indexed.",
                state="complete",
                expanded=False,
            )
        st.rerun()

    # Toggle background crawling loop
    st.sidebar.markdown("---")
    auto_loop = st.sidebar.toggle(
        "Auto-Revisit every 15 minutes",
        value=worker.is_running,
        help="Runs background crawler loop checking every 15 minutes for new posts (max 50/site).",
    )

    if auto_loop and not worker.is_running:
        worker.start(interval_seconds=900, max_per_site=50)
        st.sidebar.success("Started background crawler loop!")
        st.rerun()
    elif not auto_loop and worker.is_running:
        worker.stop()
        st.sidebar.info("Stopped background crawler loop.")
        st.rerun()

    st.sidebar.caption(
        "💡 **CLI Command:**\n```bash\npython crawler.py\n```\n"
        "Runs independently every 15 minutes."
    )


def main() -> None:
    st.title("🔍 VnExpress & BaoMoi Search Engine")
    st.caption("Full-text and text-based image search powered by Whoosh BM25F ranking")

    ix = load_cached_index()
    ix = ix.refresh()

    ix_image = load_cached_image_index()
    ix_image = ix_image.refresh()

    render_sidebar(ix, ix_image)

    search_mode = st.segmented_control(
        "Search Mode",
        options=["Articles", "Images"],
        default="Articles",
        label_visibility="collapsed",
    )

    if search_mode == "Articles":
        query = st.text_input(
            "Search query:",
            placeholder="Enter keywords (e.g., AI, technology, economy, sports)...",
            label_visibility="collapsed",
            key="query_articles",
        )

        if query.strip():
            start_time = time.perf_counter()
            results = search_documents(ix, query, limit=20)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            st.markdown(
                f"Found **{len(results)}** article(s) in **{elapsed_ms:.1f} ms** ranked by relevance:"
            )

            for rank, item in enumerate(results, start=1):
                with st.container(border=True):
                    st.markdown(f"### {rank}. [{item['title']}]({item['url']})")
                    st.markdown(f"**🔗 Link:** [{item['url']}]({item['url']})")
                    st.markdown(f"**📝 First 20 words:** {item['first_20_words']}")
                    st.caption(
                        f"📅 Published Date: {item['published_date']} | BM25F Score: {item['score']}"
                    )

    else:
        # Text-based Image Search
        query = st.text_input(
            "Image search query:",
            placeholder="Enter keywords to search images by following text (e.g., cầu vượt, giao thông, căn hộ)...",
            label_visibility="collapsed",
            key="query_images",
        )

        if query.strip():
            start_time = time.perf_counter()
            results = search_images(ix_image, query, limit=20)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            st.markdown(
                f"Found **{len(results)}** image(s) in **{elapsed_ms:.1f} ms** ranked by text relevance:"
            )

            for rank, item in enumerate(results, start=1):
                with st.container(border=True):
                    st.markdown(f"### {rank}. [{item['article_title']}]({item['article_url']})")
                    try:
                        st.image(
                            item["image_url"],
                            width="stretch",
                            caption=item["article_title"],
                        )
                    except Exception:
                        st.markdown(f"🖼️ **Image URL:** [{item['image_url']}]({item['image_url']})")
                    st.markdown(f"**📝 Text Immediately Following Image:** {item['associated_text']}")
                    st.markdown(f"**🔗 Source Article:** [{item['article_url']}]({item['article_url']})")
                    st.caption(
                        f"📅 Published Date: {item['published_date']} | BM25F Score: {item['score']}"
                    )


if __name__ == "__main__":
    main()
