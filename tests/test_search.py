from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
import pytest

from indexer import (
    _normalize_record,
    build_schema,
    get_or_create_index,
    load_dataset,
    search_documents,
)


def test_normalize_record():
    # Valid record with > 20 words snippet and alternative keys
    raw = {
        "title": "Tiêu đề bài viết",
        "url": "https://example.com/article-1",
        "content_20_words": "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twenty-one",
        "published": "2026-10-22T09:00:00+07:00",
    }
    norm = _normalize_record(raw)
    assert norm is not None
    assert norm["title"] == "Tiêu đề bài viết"
    assert norm["url"] == "https://example.com/article-1"
    assert norm["published_date"] == "2026-10-22T09:00:00+07:00"
    # Verify truncated to at most 20 words
    assert len(norm["first_20_words"].split()) == 20

    # Invalid records with empty title or url should return None
    assert _normalize_record({"title": "", "url": "https://example.com"}) is None
    assert _normalize_record({"title": "Test", "url": "  "}) is None


def test_get_or_create_index_indexes_only_once(tmp_path: Path):
    test_index_dir = tmp_path / "test_idx"
    test_data_dir = tmp_path / "test_data"
    test_data_dir.mkdir()

    # Create dummy json file
    sample_json = test_data_dir / "sample.json"
    sample_json.write_text(
        """[
            {"title": "Hacker dùng tác nhân AI tấn công doanh nghiệp", "url": "https://example.com/ai-attack", "content_20_words": "Chi tiết về mã độc AI tấn công doanh nghiệp...", "published": "2026-10-22"},
            {"title": "Thị trường vàng hôm nay", "url": "https://example.com/gold-market", "content_20_words": "Giá vàng ghi nhận biến động...", "published": "2026-10-22"}
        ]""",
        encoding="utf-8",
    )

    # First call: index does not exist, so load_dataset must be called
    with patch("indexer.load_dataset", wraps=load_dataset) as mock_load:
        ix1 = get_or_create_index(index_dir=test_index_dir, data_dir=test_data_dir)
        assert mock_load.call_count == 1
        assert ix1.doc_count() == 2

    # Second call: index already exists on disk, so load_dataset must NOT be called again
    with patch("indexer.load_dataset", wraps=load_dataset) as mock_load:
        ix2 = get_or_create_index(index_dir=test_index_dir, data_dir=test_data_dir)
        assert mock_load.call_count == 0
        assert ix2.doc_count() == 2


def test_search_documents_ranking_and_required_fields(tmp_path: Path):
    test_index_dir = tmp_path / "test_idx_search"
    test_data_dir = tmp_path / "test_data_search"
    test_data_dir.mkdir()

    sample_json = test_data_dir / "sample.json"
    sample_json.write_text(
        """[
            {
                "title": "Trí tuệ nhân tạo đột phá trong y tế",
                "url": "https://example.com/ai-health",
                "content_20_words": "Các bác sĩ ứng dụng công nghệ mới để chẩn đoán",
                "published": "2026-10-22T08:00:00+07:00"
            },
            {
                "title": "Hội thảo quốc tế tại Hà Nội",
                "url": "https://example.com/hanoi-conf",
                "content_20_words": "Chủ đề chính là trí tuệ nhân tạo và tương lai việc làm",
                "published": "2026-10-22T09:00:00+07:00"
            }
        ]""",
        encoding="utf-8",
    )

    ix = get_or_create_index(index_dir=test_index_dir, data_dir=test_data_dir)

    # Search for "trí tuệ nhân tạo"
    results = search_documents(ix, "trí tuệ nhân tạo", limit=10)
    assert len(results) == 2

    # Verify all four required fields exist in every result
    for doc in results:
        assert "title" in doc and doc["title"]
        assert "url" in doc and doc["url"]
        assert "first_20_words" in doc and doc["first_20_words"]
        assert "published_date" in doc and doc["published_date"]
        assert "score" in doc

    # Due to field_boost=2.0 on title, article with match in title should rank first
    assert results[0]["url"] == "https://example.com/ai-health"
    assert float(results[0]["score"]) >= float(results[1]["score"])


def test_search_documents_empty_query(tmp_path: Path):
    test_index_dir = tmp_path / "test_empty_idx"
    test_data_dir = tmp_path / "test_empty_data"
    test_data_dir.mkdir()

    ix = get_or_create_index(index_dir=test_index_dir, data_dir=test_data_dir)
    assert search_documents(ix, "") == []
    assert search_documents(ix, "   ") == []
