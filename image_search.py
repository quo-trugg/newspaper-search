from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from whoosh import index, scoring
from whoosh.fields import ID, STORED, TEXT, Schema
from whoosh.qparser import MultifieldParser, OrGroup

logger = logging.getLogger("ImageSearch")


def build_image_schema() -> Schema:
    """Whoosh schema for text-based image search over article subdocuments."""
    return Schema(
        doc_id=ID(stored=True, unique=True),
        image_url=STORED,
        article_url=STORED,
        article_title=TEXT(stored=True, field_boost=1.5),
        associated_text=TEXT(stored=True, field_boost=2.5),
        published_date=STORED,
    )


def extract_image_subdocuments(
    html: str,
    page_url: str,
    article_title: str = "",
    published_date: str = "",
) -> list[dict[str, str]]:
    """Split a web page HTML into multiple image subdocuments.
    
    For each image in the page, extracts the image URL and the text content
    immediately following the image (captions, adjacent paragraphs, or descriptions).
    """
    if not html or not page_url:
        return []

    soup = BeautifulSoup(html, "html.parser")
    subdocuments: list[dict[str, str]] = []
    seen_image_urls: set[str] = set()

    # 1. Check for BaoMoi structured __NEXT_DATA__
    next_data_script = soup.find("script", id="__NEXT_DATA__")
    if next_data_script and next_data_script.string:
        try:
            data = json.loads(next_data_script.string)
            content = (
                data.get("props", {})
                .get("pageProps", {})
                .get("resp", {})
                .get("data", {})
                .get("content", {})
            )
            bodys = content.get("bodys", [])
            bm_title = article_title or content.get("title", "")
            bm_pub = published_date or str(content.get("publishedDate") or content.get("date") or "")

            for i, item in enumerate(bodys):
                if item.get("type") == "image" and item.get("content"):
                    raw_src = item.get("content")
                    img_url = urljoin(page_url, raw_src)
                    if img_url in seen_image_urls:
                        continue

                    # Text content immediately following the image
                    assoc_text = ""
                    if i + 1 < len(bodys) and bodys[i + 1].get("type") == "text":
                        raw_text = bodys[i + 1].get("content", "")
                        assoc_text = re.sub(r"<[^>]+>", " ", raw_text).strip()
                    if not assoc_text and item.get("description"):
                        assoc_text = str(item.get("description")).strip()

                    if assoc_text:
                        seen_image_urls.add(img_url)
                        doc_id = hashlib.sha1(f"{page_url}#{img_url}".encode("utf-8")).hexdigest()
                        subdocuments.append(
                            {
                                "doc_id": doc_id,
                                "image_url": img_url,
                                "article_url": page_url,
                                "article_title": bm_title,
                                "associated_text": assoc_text,
                                "published_date": bm_pub,
                            }
                        )
        except Exception as err:
            logger.debug(f"Could not parse __NEXT_DATA__ for images: {err}")

    if subdocuments:
        return subdocuments

    # 2. General HTML extraction for VnExpress and other article structures
    # Locate figures, picture tags, or content images
    figures = soup.find_all(
        ["figure", "div"],
        class_=lambda c: c and any(k in str(c) for k in ["fig-img", "tplCaption", "picture", "item_slide_show"]),
    )
    if not figures:
        figures = soup.find_all("figure")

    for fig in figures:
        img = fig.find("img")
        if not img:
            continue

        raw_src = img.get("data-src") or img.get("src") or ""
        if not raw_src or raw_src.startswith("data:") or ".svg" in raw_src:
            continue

        img_url = urljoin(page_url, raw_src)
        if img_url in seen_image_urls:
            continue

        # Extract caption tag immediately within or following the image
        caption_tag = fig.find(["figcaption", "p", "em", "span"], class_=lambda c: c and any(k in str(c) for k in ["caption", "desc", "title"])) or fig.find(["figcaption", "em"])
        caption_text = caption_tag.get_text(" ", strip=True) if caption_tag else ""

        # Extract next sibling paragraph / text content immediately following the figure
        next_sibling = fig.find_next_sibling(["p", "div"])
        next_text = next_sibling.get_text(" ", strip=True) if next_sibling else ""

        # Combine text content immediately following the image
        parts = [p for p in [caption_text, next_text] if p]
        associated_text = " - ".join(parts) if parts else img.get("alt", "").strip()

        if associated_text:
            seen_image_urls.add(img_url)
            doc_id = hashlib.sha1(f"{page_url}#{img_url}".encode("utf-8")).hexdigest()
            subdocuments.append(
                {
                    "doc_id": doc_id,
                    "image_url": img_url,
                    "article_url": page_url,
                    "article_title": article_title or (soup.find("h1").get_text().strip() if soup.find("h1") else ""),
                    "associated_text": associated_text,
                    "published_date": published_date,
                }
            )

    return subdocuments


def load_image_dataset(data_path: str | Path = "data/images_dataset.json") -> list[dict[str, str]]:
    """Load image subdocuments from JSON dataset file."""
    path = Path(data_path)
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and d.get("image_url") and d.get("associated_text")]
    except Exception as err:
        logger.warning(f"Failed to read image dataset from {data_path}: {err}")
    return []


def save_image_subdocuments(
    subdocs: list[dict[str, str]],
    data_path: str | Path = "data/images_dataset.json",
) -> None:
    """Save or append image subdocuments to data_path in UTF-8 JSON format."""
    if not subdocs:
        return

    path = Path(data_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_image_dataset(path)
    known_ids = {d.get("doc_id") for d in existing}

    for doc in subdocs:
        d_id = doc.get("doc_id")
        if d_id and d_id not in known_ids:
            existing.append(doc)
            known_ids.add(d_id)

    with path.open("w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def get_or_create_image_index(
    index_dir: str | Path = "image_indexdir",
    data_file: str | Path = "data/images_dataset.json",
) -> index.Index:
    """Open existing Whoosh image index if present on disk, or create and populate it once."""
    index_path = str(index_dir)

    if os.path.exists(index_path) and index.exists_in(index_path):
        return index.open_dir(index_path)

    os.makedirs(index_path, exist_ok=True)
    ix = index.create_in(index_path, build_image_schema())
    subdocs = load_image_dataset(data_file)

    if subdocs:
        writer = ix.writer()
        for doc in subdocs:
            writer.update_document(
                doc_id=doc.get("doc_id") or hashlib.sha1(f"{doc['article_url']}#{doc['image_url']}".encode("utf-8")).hexdigest(),
                image_url=doc["image_url"],
                article_url=doc["article_url"],
                article_title=doc.get("article_title", ""),
                associated_text=doc.get("associated_text", ""),
                published_date=doc.get("published_date", ""),
            )
        writer.commit()

    return ix


def index_image_subdocuments(ix: index.Index, subdocs: list[dict[str, str]]) -> int:
    """Batch index new or updated image subdocuments into Whoosh."""
    if not subdocs:
        return 0

    writer = ix.writer()
    for doc in subdocs:
        doc_id = doc.get("doc_id") or hashlib.sha1(f"{doc['article_url']}#{doc['image_url']}".encode("utf-8")).hexdigest()
        writer.update_document(
            doc_id=doc_id,
            image_url=doc["image_url"],
            article_url=doc["article_url"],
            article_title=doc.get("article_title", ""),
            associated_text=doc.get("associated_text", ""),
            published_date=doc.get("published_date", ""),
        )
    writer.commit()
    return len(subdocs)


def search_images(
    ix: index.Index,
    query_str: str,
    limit: int = 20,
) -> list[dict[str, str]]:
    """Search image subdocuments comparing the query against text content immediately following each image."""
    clean_query = query_str.strip()
    if not clean_query:
        return []

    parser = MultifieldParser(
        ["associated_text", "article_title"],
        schema=ix.schema,
        group=OrGroup,
    )
    parsed_query = parser.parse(clean_query)

    results: list[dict[str, str]] = []
    with ix.searcher(weighting=scoring.BM25F()) as searcher:
        hits = searcher.search(parsed_query, limit=limit)
        for hit in hits:
            results.append(
                {
                    "doc_id": hit.get("doc_id", ""),
                    "image_url": hit.get("image_url", ""),
                    "article_url": hit.get("article_url", ""),
                    "article_title": hit.get("article_title", ""),
                    "associated_text": hit.get("associated_text", ""),
                    "published_date": hit.get("published_date", ""),
                    "score": f"{hit.score:.3f}",
                }
            )
    return results
