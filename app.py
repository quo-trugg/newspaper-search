from __future__ import annotations

import time
import streamlit as st
from indexer import get_or_create_index, search_documents

st.set_page_config(
    page_title="VnExpress & BaoMoi Search Engine",
    page_icon="🔍",
    layout="centered",
)


@st.cache_resource(show_spinner="Initializing search index...")
def load_cached_index():
    """Load or initialize the Whoosh search index once and cache the reference."""
    return get_or_create_index(index_dir="indexdir", data_dir="data")


def main() -> None:
    st.title("🔍 VnExpress & BaoMoi Search Engine")
    st.caption("Full-text search powered by Whoosh BM25F ranking and Streamlit")

    ix = load_cached_index()

    col1, col2 = st.columns([4, 1])
    with col1:
        query = st.text_input(
            "Search query:",
            placeholder="Nhập từ khóa (ví dụ: AI, công nghệ, kinh tế, thể thao)...",
            label_visibility="collapsed",
        )
    with col2:
        top_k = st.selectbox(
            "Limit",
            options=[10, 20, 50, 100],
            index=1,
            label_visibility="collapsed",
        )

    if query.strip():
        start_time = time.perf_counter()
        results = search_documents(ix, query, limit=top_k)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        st.markdown(
            f"Found **{len(results)}** result(s) in **{elapsed_ms:.1f} ms** ranked by relevance:"
        )

        for rank, item in enumerate(results, start=1):
            with st.container(border=True):
                st.markdown(f"### {rank}. [{item['title']}]({item['url']})")
                st.markdown(f"**🔗 Link:** [{item['url']}]({item['url']})")
                st.markdown(f"**📝 First 20 words:** {item['first_20_words']}")
                st.caption(f"📅 Published Date: {item['published_date']} | BM25F Score: {item['score']}")
    else:
        st.info("💡 Enter one or more keywords above to search news articles from VnExpress and BaoMoi.")


if __name__ == "__main__":
    main()
