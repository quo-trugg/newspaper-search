from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from whoosh import index

from image_search import (
    build_image_schema,
    extract_image_subdocuments,
    get_or_create_image_index,
    index_image_subdocuments,
    load_image_dataset,
    save_image_subdocuments,
    search_images,
)


def test_extract_image_subdocuments_html_figure():
    sample_html = """
    <html>
      <body>
        <h1>Cải tạo căn hộ cũ</h1>
        <figure class="tplCaption">
          <img src="/images/living_room.jpg" alt="Phòng khách" />
          <figcaption class="caption">Phòng khách hiện đại với sofa màu kem</figcaption>
        </figure>
        <p>Gia chủ dành nhiều tâm huyết cho không gian sinh hoạt chung.</p>

        <figure class="tplCaption">
          <img src="https://example.com/kitchen.png" alt="Phòng bếp" />
        </figure>
        <p>Khu vực bếp được lát gạch men chống bám dầu mỡ sáng bóng.</p>
      </body>
    </html>
    """
    subdocs = extract_image_subdocuments(
        html=sample_html,
        page_url="https://example.com/bai-viet-1.html",
        article_title="Cải tạo căn hộ cũ",
        published_date="2026-10-26",
    )

    assert len(subdocs) == 2
    # First image subdocument
    doc1 = subdocs[0]
    assert doc1["image_url"] == "https://example.com/images/living_room.jpg"
    assert doc1["article_url"] == "https://example.com/bai-viet-1.html"
    assert doc1["article_title"] == "Cải tạo căn hộ cũ"
    assert "Phòng khách hiện đại với sofa màu kem" in doc1["associated_text"]
    assert "Gia chủ dành nhiều tâm huyết" in doc1["associated_text"]

    # Second image subdocument (uses following sibling <p>)
    doc2 = subdocs[1]
    assert doc2["image_url"] == "https://example.com/kitchen.png"
    assert "Khu vực bếp được lát gạch men" in doc2["associated_text"]


def test_extract_image_subdocuments_baomoi_next_data():
    sample_next_data_html = """
    <html>
      <body>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "resp": {
                "data": {
                  "content": {
                    "title": "Nút giao thông La Thành thông thoáng",
                    "publishedDate": "2026-10-26T12:00:00",
                    "bodys": [
                      {
                        "type": "image",
                        "content": "https://photo.example.com/nut_giao.jpg",
                        "description": "Hình ảnh nút giao"
                      },
                      {
                        "type": "text",
                        "content": "<p>Lực lượng cảnh sát giao thông điều tiết phương tiện giờ cao điểm.</p>"
                      }
                    ]
                  }
                }
              }
            }
          }
        }
        </script>
      </body>
    </html>
    """
    subdocs = extract_image_subdocuments(
        html=sample_next_data_html,
        page_url="https://baomoi.com/nut-giao-c123.epi",
    )

    assert len(subdocs) == 1
    doc = subdocs[0]
    assert doc["image_url"] == "https://photo.example.com/nut_giao.jpg"
    assert doc["article_url"] == "https://baomoi.com/nut-giao-c123.epi"
    assert doc["article_title"] == "Nút giao thông La Thành thông thoáng"
    assert doc["associated_text"] == "Lực lượng cảnh sát giao thông điều tiết phương tiện giờ cao điểm."


def test_get_or_create_image_index_indexes_once(tmp_path: Path):
    test_index_dir = tmp_path / "img_idx"
    test_data_file = tmp_path / "img_data.json"

    test_data_file.write_text(
        json.dumps(
            [
                {
                    "doc_id": "id1",
                    "image_url": "https://example.com/img1.jpg",
                    "article_url": "https://example.com/art1",
                    "article_title": "Bài 1",
                    "associated_text": "Cầu vượt trên cao đang thi công hạng mục dầm thép",
                    "published_date": "2026-10-26",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # First call: index created
    with patch("image_search.load_image_dataset", wraps=load_image_dataset) as mock_load:
        ix1 = get_or_create_image_index(index_dir=test_index_dir, data_file=test_data_file)
        assert mock_load.call_count == 1
        assert ix1.doc_count() == 1

    # Second call: index already exists, load_image_dataset not called
    with patch("image_search.load_image_dataset", wraps=load_image_dataset) as mock_load:
        ix2 = get_or_create_image_index(index_dir=test_index_dir, data_file=test_data_file)
        assert mock_load.call_count == 0
        assert ix2.doc_count() == 1


def test_search_images_bm25f(tmp_path: Path):
    test_index_dir = tmp_path / "img_search_idx"
    test_data_file = tmp_path / "img_data_search.json"

    subdocs = [
        {
            "doc_id": "img_bridge",
            "image_url": "https://example.com/bridge.jpg",
            "article_url": "https://example.com/bridge-news",
            "article_title": "Tiến độ hạ tầng giao thông",
            "associated_text": "Cầu vượt chữ C tại ngã tư được lắp đặt kết cấu vòm thép chịu lực",
            "published_date": "2026-10-26",
        },
        {
            "doc_id": "img_football",
            "image_url": "https://example.com/football.jpg",
            "article_url": "https://example.com/sports-news",
            "article_title": "Trận đấu giải ngoại hạng",
            "associated_text": "Cầu thủ ăn mừng bàn thắng ấn định tỉ số trận đấu",
            "published_date": "2026-10-26",
        },
    ]
    test_data_file.write_text(json.dumps(subdocs, ensure_ascii=False), encoding="utf-8")

    ix = get_or_create_image_index(index_dir=test_index_dir, data_file=test_data_file)

    # Search for "vòm thép"
    hits = search_images(ix, "vòm thép")
    assert len(hits) == 1
    assert hits[0]["doc_id"] == "img_bridge"
    assert hits[0]["image_url"] == "https://example.com/bridge.jpg"
    assert "vòm thép" in hits[0]["associated_text"].lower()
    assert float(hits[0]["score"]) > 0

    # Search for "cầu vượt" ranks bridge higher than football ("cầu thủ")
    hits_or = search_images(ix, "cầu vượt")
    assert hits_or[0]["doc_id"] == "img_bridge"
    assert float(hits_or[0]["score"]) > float(hits_or[1]["score"])

    # Search for empty
    assert search_images(ix, "") == []
    assert search_images(ix, "   ") == []


def test_search_images_collapses_multiple_images_per_article(tmp_path: Path):
    test_index_dir = tmp_path / "img_collapse_idx"
    test_data_file = tmp_path / "img_collapse_data.json"

    # Same article has 3 different images all matching "công nghệ"
    subdocs = [
        {
            "doc_id": "img_art1_photo1",
            "image_url": "https://example.com/photo1.jpg",
            "article_url": "https://example.com/same-article-1",
            "article_title": "Triển lãm công nghệ",
            "associated_text": "Robot công nghệ cao hỗ trợ y tế thông minh",
            "published_date": "2026-10-26",
        },
        {
            "doc_id": "img_art1_photo2",
            "image_url": "https://example.com/photo2.jpg",
            "article_url": "https://example.com/same-article-1",
            "article_title": "Triển lãm công nghệ",
            "associated_text": "Khu trưng bày công nghệ vi mạch bán dẫn tiên tiến",
            "published_date": "2026-10-26",
        },
        {
            "doc_id": "img_art1_photo3",
            "image_url": "https://example.com/photo3.jpg",
            "article_url": "https://example.com/same-article-1",
            "article_title": "Triển lãm công nghệ",
            "associated_text": "Khách tham quan gian hàng công nghệ thực tế ảo",
            "published_date": "2026-10-26",
        },
        {
            "doc_id": "img_art2_photo1",
            "image_url": "https://example.com/other_photo.jpg",
            "article_url": "https://example.com/different-article-2",
            "article_title": "Hội nghị phần mềm",
            "associated_text": "Các chuyên gia trao đổi về công nghệ đám mây",
            "published_date": "2026-10-26",
        },
    ]
    test_data_file.write_text(json.dumps(subdocs, ensure_ascii=False), encoding="utf-8")

    ix = get_or_create_image_index(index_dir=test_index_dir, data_file=test_data_file)

    # When searching for "công nghệ", all 4 images match, but the 3 images from article 1 must collapse into 1
    hits = search_images(ix, "công nghệ", limit=10, collapse_by_article=True)

    # Must contain exactly 2 hits: 1 for article 1 and 1 for article 2
    assert len(hits) == 2
    returned_articles = [h["article_url"] for h in hits]
    assert len(returned_articles) == len(set(returned_articles))
    assert "https://example.com/same-article-1" in returned_articles
    assert "https://example.com/different-article-2" in returned_articles
