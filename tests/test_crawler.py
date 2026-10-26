from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from whoosh import index

from crawler import (
    clean_url,
    crawl_and_index_revisit,
    crawl_baomoi,
    crawl_vnexpress,
    get_known_urls,
    run_crawler_loop,
    save_crawled_records,
)
from indexer import build_schema, get_indexed_urls, get_or_create_index, search_documents


def test_clean_url():
    assert clean_url("  https://vnexpress.net/bai-viet-123.html#box_comment  ") == "https://vnexpress.net/bai-viet-123.html"
    assert clean_url("https://baomoi.com/bai-viet-c123.epi/") == "https://baomoi.com/bai-viet-c123.epi"
    assert clean_url("") == ""


def test_crawl_vnexpress_skips_seen_urls_and_respects_max():
    sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Tin mới nhất</title>
        <item>
          <title>Tin số 1 - Đã xem</title>
          <link>https://vnexpress.net/tin-1.html</link>
          <description><![CDATA[<a href="..."><img src="..."/></a></br>Mô tả ngắn của bài viết số 1 với một vài từ ngữ]]></description>
          <pubDate>Mon, 26 Oct 2026 10:00:00 +0700</pubDate>
        </item>
        <item>
          <title>Tin số 2 - Bài mới</title>
          <link>https://vnexpress.net/tin-2.html#comment</link>
          <description>Mô tả bài viết số hai có nội dung công nghệ mới cập nhật trong ngày</description>
          <pubDate>Mon, 26 Oct 2026 10:05:00 +0700</pubDate>
        </item>
        <item>
          <title>Tin số 3 - Bài mới thứ hai</title>
          <link>https://vnexpress.net/tin-3.html</link>
          <description>Một bài viết nữa về chủ đề kinh tế thị trường tài chính</description>
          <pubDate>Mon, 26 Oct 2026 10:10:00 +0700</pubDate>
        </item>
      </channel>
    </rss>
    """
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = sample_rss.encode("utf-8")
    mock_session.get.return_value = mock_resp

    seen_urls = {"https://vnexpress.net/tin-1.html"}

    # Limit to max 1 new post
    results = crawl_vnexpress(seen_urls=seen_urls, max_posts=1, session=mock_session)

    assert len(results) == 1
    assert results[0]["url"] == "https://vnexpress.net/tin-2.html"
    assert results[0]["title"] == "Tin số 2 - Bài mới"
    assert "https://vnexpress.net/tin-2.html" in seen_urls
    assert len(results[0]["first_20_words"].split()) <= 20


def test_crawl_baomoi_skips_seen_urls_and_respects_max():
    mock_listing_html = """
    <html>
      <body>
        <a href="/bai-viet-1-c111.epi">Bài 1</a>
        <a href="/bai-viet-2-c222.epi">Bài 2</a>
        <a href="/bai-viet-3-c333.epi">Bài 3</a>
      </body>
    </html>
    """
    mock_article_html = """
    <html>
      <head>
        <meta property="article:published_time" content="2026-10-26T10:00:00+07:00" />
        <meta name="description" content="Tóm tắt ngắn gọn bài báo bao gồm các nội dung cốt lõi nhất được ghi nhận" />
      </head>
      <body>
        <h1>Tiêu đề bài viết BaoMoi mới</h1>
      </body>
    </html>
    """

    mock_session = MagicMock()

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "tin-moi" in url:
            resp.text = mock_listing_html
        else:
            resp.text = mock_article_html
        return resp

    mock_session.get.side_effect = mock_get

    seen_urls = {"https://baomoi.com/bai-viet-1-c111.epi"}

    # Limit to 1 post
    results = crawl_baomoi(seen_urls=seen_urls, max_posts=1, session=mock_session)

    assert len(results) == 1
    assert results[0]["url"] == "https://baomoi.com/bai-viet-2-c222.epi"
    assert results[0]["title"] == "Tiêu đề bài viết BaoMoi mới"
    assert results[0]["published_date"] == "2026-10-26T10:00:00+07:00"
    assert "https://baomoi.com/bai-viet-2-c222.epi" in seen_urls


def test_crawl_and_index_revisit_full_flow(tmp_path: Path):
    test_index_dir = tmp_path / "indexdir"
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir()

    # Create dummy initial data file
    sample_file = test_data_dir / "init.json"
    sample_file.write_text(
        json.dumps(
            [
                {
                    "title": "Tin ban đầu",
                    "url": "https://vnexpress.net/tin-cu.html",
                    "first_20_words": "Nội dung tin cũ đã có trong hệ thống",
                    "published_date": "2026-10-20",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Pre-index
    ix = get_or_create_index(index_dir=test_index_dir, data_dir=test_data_dir)
    assert ix.doc_count() == 1

    # Mock vnexpress and baomoi crawler outputs
    new_vne = [
        {
            "title": "Hàng không tăng chuyến bay Tết",
            "url": "https://vnexpress.net/hang-khong-tang-chuyen-5001.html",
            "first_20_words": "Các hãng hàng không Việt Nam mở bán vé Tết sớm",
            "published_date": "2026-10-26T10:00:00+07:00",
        }
    ]
    new_bm = [
        {
            "title": "Thị trường bất động sản phục hồi",
            "url": "https://baomoi.com/thi-truong-bds-phuc-hoi-c5002.epi",
            "first_20_words": "Giao dịch bất động sản ghi nhận tín hiệu khởi sắc",
            "published_date": "2026-10-26T10:05:00+07:00",
        }
    ]

    with patch("crawler.crawl_vnexpress", return_value=new_vne) as mock_vne, \
         patch("crawler.crawl_baomoi", return_value=new_bm) as mock_bm:

        summary = crawl_and_index_revisit(
            index_dir=test_index_dir,
            data_dir=test_data_dir,
            max_per_site=50,
        )

        assert summary["total_new"] == 2
        assert summary["vnexpress_new"] == 1
        assert summary["baomoi_new"] == 1
        assert summary["total_docs"] == 3

        # Verify newly crawled articles can immediately be searched
        hits = search_documents(ix.refresh(), "hàng không")
        assert len(hits) == 1
        assert hits[0]["url"] == "https://vnexpress.net/hang-khong-tang-chuyen-5001.html"

        hits_bm = search_documents(ix.refresh(), "bất động sản")
        assert len(hits_bm) == 1
        assert hits_bm[0]["url"] == "https://baomoi.com/thi-truong-bds-phuc-hoi-c5002.epi"

        # Verify cumulative json file was saved
        cum_file = test_data_dir / "crawled_articles.json"
        assert cum_file.exists()
        saved_records = json.loads(cum_file.read_text(encoding="utf-8"))
        assert len(saved_records) == 2


def test_crawl_revisit_skips_already_crawled_on_next_revisit(tmp_path: Path):
    test_index_dir = tmp_path / "indexdir"
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir()

    ix = get_or_create_index(index_dir=test_index_dir, data_dir=test_data_dir)

    posts_first_round = [
        {
            "title": "Bài viết test",
            "url": "https://vnexpress.net/bai-test-1.html",
            "first_20_words": "Nội dung bài viết",
            "published_date": "2026-10-26",
        }
    ]

    # First revisit adds 1 post
    with patch("crawler.crawl_vnexpress", return_value=posts_first_round), \
         patch("crawler.crawl_baomoi", return_value=[]):
        res1 = crawl_and_index_revisit(index_dir=test_index_dir, data_dir=test_data_dir)
        assert res1["total_new"] == 1

    # On second revisit, seen_urls contains the post from round 1
    known = get_known_urls(data_dir=test_data_dir, index_dir=test_index_dir)
    assert "https://vnexpress.net/bai-test-1.html" in known

    # Since seen_urls now has it, crawl_vnexpress should not yield it
    with patch("crawler.crawl_vnexpress", return_value=[]), \
         patch("crawler.crawl_baomoi", return_value=[]):
        res2 = crawl_and_index_revisit(
            index_dir=test_index_dir,
            data_dir=test_data_dir,
            seen_urls=known,
        )
        assert res2["total_new"] == 0


def test_run_crawler_loop_stops_on_event(tmp_path: Path):
    test_index_dir = tmp_path / "indexdir"
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir()

    stop_event = threading.Event()
    call_count = 0

    def mock_cycle(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        stop_event.set()  # Stop after first run
        return {"total_new": 0}

    with patch("crawler.crawl_and_index_revisit", side_effect=mock_cycle):
        run_crawler_loop(
            interval_seconds=1,
            data_dir=test_data_dir,
            index_dir=test_index_dir,
            stop_event=stop_event,
        )

    assert call_count == 1
