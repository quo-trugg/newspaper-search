from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

from image_search import (
    extract_image_subdocuments,
    get_or_create_image_index,
    index_image_subdocuments,
    save_image_subdocuments,
)
from indexer import (
    _normalize_record,
    get_indexed_urls,
    get_or_create_index,
    index_records,
    load_dataset,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("CrawlerLoop")

DEFAULT_INTERVAL_SECONDS = 15 * 60  # 15 minutes
DEFAULT_MAX_NEW_POSTS_PER_SITE = 50

VNEXPRESS_RSS_FEEDS = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://vnexpress.net/rss/thoi-su.rss",
    "https://vnexpress.net/rss/the-gioi.rss",
    "https://vnexpress.net/rss/kinh-doanh.rss",
    "https://vnexpress.net/rss/giai-tri.rss",
    "https://vnexpress.net/rss/the-thao.rss",
]

BAOMOI_LISTING_URLS = [
    "https://baomoi.com/tin-moi.epi",
    "https://baomoi.com/tin-moi/trang-2.epi",
    "https://baomoi.com/tin-moi/trang-3.epi",
]

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}


def clean_url(url: str) -> str:
    """Normalize URL by stripping whitespace, trailing slashes, and hash fragments."""
    if not url:
        return ""
    clean = url.strip()
    clean = re.sub(r"#.*$", "", clean)
    if clean.endswith("/") and len(clean) > len("https://x.co/"):
        clean = clean.rstrip("/")
    return clean


def get_known_urls(
    data_dir: str | Path = "data",
    index_dir: str | Path = "indexdir",
) -> set[str]:
    """Collect all URLs that have already been crawled and stored in data/ or Whoosh index."""
    seen_urls: set[str] = set()

    # 1. From existing Whoosh index if available
    try:
        ix = get_or_create_index(index_dir=index_dir, data_dir=data_dir)
        seen_urls.update(get_indexed_urls(ix))
    except Exception as e:
        logger.warning(f"Could not read URLs from Whoosh index: {e}")

    # 2. From dataset files in data_dir
    try:
        data_records = load_dataset(data_dir)
        for r in data_records:
            if r.get("url"):
                seen_urls.add(clean_url(r["url"]))
    except Exception as e:
        logger.warning(f"Could not read URLs from data files: {e}")

    # 3. From crawler state / cumulative file if present
    cumulative_file = Path(data_dir) / "crawled_articles.json"
    if cumulative_file.exists():
        try:
            with cumulative_file.open("r", encoding="utf-8") as f:
                records = json.load(f)
                if isinstance(records, list):
                    for r in records:
                        if isinstance(r, dict) and r.get("url"):
                            seen_urls.add(clean_url(r["url"]))
        except Exception as e:
            logger.warning(f"Could not read cumulative crawled file: {e}")

    return {clean_url(u) for u in seen_urls if u}


def crawl_vnexpress(
    seen_urls: set[str],
    max_posts: int = DEFAULT_MAX_NEW_POSTS_PER_SITE,
    session: requests.Session | None = None,
) -> list[dict[str, str]]:
    """Crawl new articles from VnExpress RSS feeds up to max_posts. Skips existing URLs."""
    if session is None:
        session = requests.Session()
        session.headers.update(HTTP_HEADERS)

    new_articles: list[dict[str, str]] = []

    for feed_url in VNEXPRESS_RSS_FEEDS:
        if len(new_articles) >= max_posts:
            break

        try:
            resp = session.get(feed_url, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch VnExpress feed {feed_url}: status {resp.status_code}")
                continue

            root = ET.fromstring(resp.content)
            items = root.findall(".//item")

            for item in items:
                if len(new_articles) >= max_posts:
                    break

                raw_link = item.findtext("link") or ""
                url = clean_url(raw_link)
                if not url or url in seen_urls:
                    continue

                title = (item.findtext("title") or "").strip()
                if not title:
                    continue

                pub_date = (item.findtext("pubDate") or "").strip() or datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat()

                desc_raw = item.findtext("description") or ""
                # Strip HTML tags from description to extract text snippet
                desc_text = re.sub(r"<[^>]+>", " ", desc_raw).strip()
                words = desc_text.split()
                first_20_words = " ".join(words[:20])

                norm = _normalize_record(
                    {
                        "url": url,
                        "title": title,
                        "published_date": pub_date,
                        "first_20_words": first_20_words,
                    }
                )
                if norm and norm["url"] not in seen_urls:
                    seen_urls.add(norm["url"])
                    new_articles.append(norm)

        except Exception as err:
            logger.warning(f"Error parsing VnExpress RSS feed {feed_url}: {err}")

    return new_articles


def _fetch_baomoi_article(
    url: str,
    session: requests.Session,
) -> dict[str, str] | None:
    """Fetch an individual BaoMoi article page and extract title, snippet, and date."""
    try:
        resp = session.get(url, timeout=8)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        h1 = soup.find("h1")
        title = h1.get_text().strip() if h1 else ""

        if not title:
            og_title = soup.find("meta", {"property": "og:title"})
            if og_title and og_title.get("content"):
                title = str(og_title["content"]).strip()

        if not title:
            return None

        meta_desc = soup.find("meta", {"name": "description"}) or soup.find(
            "meta", {"property": "og:description"}
        )
        first_20_words = ""
        if meta_desc and meta_desc.get("content"):
            words = str(meta_desc["content"]).strip().split()
            first_20_words = " ".join(words[:20])
        else:
            first_p = soup.find("p")
            if first_p:
                words = first_p.get_text().strip().split()
                first_20_words = " ".join(words[:20])

        meta_pub = soup.find("meta", {"property": "article:published_time"})
        if meta_pub and meta_pub.get("content"):
            pub_date = str(meta_pub["content"]).strip()
        else:
            time_tag = soup.find("time")
            pub_date = (
                time_tag.get_text().strip()
                if time_tag
                else datetime.datetime.now(datetime.timezone.utc).isoformat()
            )

        return _normalize_record(
            {
                "url": url,
                "title": title,
                "first_20_words": first_20_words,
                "published_date": pub_date,
            }
        )
    except Exception as err:
        logger.debug(f"Failed to fetch BaoMoi article {url}: {err}")
        return None


def crawl_baomoi(
    seen_urls: set[str],
    max_posts: int = DEFAULT_MAX_NEW_POSTS_PER_SITE,
    session: requests.Session | None = None,
) -> list[dict[str, str]]:
    """Crawl new articles from BaoMoi latest listing up to max_posts. Skips existing URLs."""
    if session is None:
        session = requests.Session()
        session.headers.update(HTTP_HEADERS)

    candidate_urls: list[str] = []

    for listing_url in BAOMOI_LISTING_URLS:
        if len(candidate_urls) >= max_posts:
            break

        try:
            resp = session.get(listing_url, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch BaoMoi listing {listing_url}: status {resp.status_code}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if re.search(r"-c\d+\.epi$", href):
                    full_url = clean_url(
                        f"https://baomoi.com{href}" if href.startswith("/") else href
                    )
                    if (
                        full_url
                        and full_url not in seen_urls
                        and full_url not in candidate_urls
                    ):
                        candidate_urls.append(full_url)
                        if len(candidate_urls) >= max_posts:
                            break
        except Exception as err:
            logger.warning(f"Error fetching BaoMoi listing {listing_url}: {err}")

    if not candidate_urls:
        return []

    new_articles: list[dict[str, str]] = []
    # Fetch article details concurrently for performance
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(_fetch_baomoi_article, url, session)
            for url in candidate_urls[:max_posts]
        ]
        for f in futures:
            try:
                res = f.result()
                if res and res["url"] not in seen_urls:
                    seen_urls.add(res["url"])
                    new_articles.append(res)
            except Exception as e:
                logger.debug(f"Error retrieving parsed BaoMoi article: {e}")

    return new_articles[:max_posts]


def save_crawled_records(
    records: list[dict[str, str]],
    data_dir: str | Path = "data",
) -> Path | None:
    """Save new crawled records to data_dir in UTF-8 JSON format."""
    if not records:
        return None

    path_data = Path(data_dir)
    path_data.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_file = path_data / f"crawled_batch_{timestamp}.json"

    # Write batch file
    with batch_file.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    # Append to cumulative crawled articles file
    cumulative_file = path_data / "crawled_articles.json"
    all_crawled: list[dict[str, str]] = []
    if cumulative_file.exists():
        try:
            with cumulative_file.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    all_crawled = loaded
        except Exception as e:
            logger.warning(f"Could not load cumulative file: {e}")

    existing_urls = {r.get("url") for r in all_crawled if isinstance(r, dict)}
    for r in records:
        if r["url"] not in existing_urls:
            all_crawled.append(r)
            existing_urls.add(r["url"])

    with cumulative_file.open("w", encoding="utf-8") as f:
        json.dump(all_crawled, f, ensure_ascii=False, indent=2)

    return batch_file


def save_crawler_status(
    status_data: dict[str, Any],
    data_dir: str | Path = "data",
) -> None:
    """Persist current crawler state to data/.crawler_status.json."""
    status_path = Path(data_dir) / ".crawler_status.json"
    try:
        with status_path.open("w", encoding="utf-8") as f:
            json.dump(status_data, f, ensure_ascii=False, indent=2)
    except Exception as err:
        logger.warning(f"Could not save crawler status: {err}")


def get_crawler_status(data_dir: str | Path = "data") -> dict[str, Any]:
    """Read the latest crawler status if available."""
    status_path = Path(data_dir) / ".crawler_status.json"
    if status_path.exists():
        try:
            with status_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "last_run": "Never",
        "vnexpress_new": 0,
        "baomoi_new": 0,
        "total_new": 0,
        "status": "Idle",
    }


def crawl_and_index_revisit(
    index_dir: str | Path = "indexdir",
    data_dir: str | Path = "data",
    image_index_dir: str | Path = "image_indexdir",
    max_per_site: int = DEFAULT_MAX_NEW_POSTS_PER_SITE,
    seen_urls: set[str] | None = None,
) -> dict[str, Any]:
    """Execute a single revisit cycle:
    1. Detect all known URLs (skips already crawled content)
    2. Crawl up to max_per_site new posts from VnExpress
    3. Crawl up to max_per_site new posts from BaoMoi
    4. Save new content to data/
    5. Index new content into Whoosh article index & image index
    """
    logger.info("--- Starting Revisit Cycle ---")
    start_time = time.time()

    ix = get_or_create_index(index_dir=index_dir, data_dir=data_dir)

    if seen_urls is None:
        seen_urls = get_known_urls(data_dir=data_dir, index_dir=index_dir)
    initial_known_count = len(seen_urls)
    logger.info(f"Loaded {initial_known_count} already-crawled URLs to skip.")

    # 1. Crawl VnExpress
    logger.info(f"Checking VnExpress (max {max_per_site} new posts)...")
    vne_articles = crawl_vnexpress(seen_urls=seen_urls, max_posts=max_per_site)
    logger.info(f"VnExpress: Found {len(vne_articles)} new post(s).")

    # 2. Crawl BaoMoi
    logger.info(f"Checking BaoMoi (max {max_per_site} new posts)...")
    bm_articles = crawl_baomoi(seen_urls=seen_urls, max_posts=max_per_site)
    logger.info(f"BaoMoi: Found {len(bm_articles)} new post(s).")

    new_articles = vne_articles + bm_articles
    indexed_count = 0
    new_images_count = 0

    if new_articles:
        logger.info(f"Saving {len(new_articles)} new articles to '{data_dir}'...")
        save_crawled_records(new_articles, data_dir=data_dir)

        logger.info(f"Indexing {len(new_articles)} new articles into Whoosh '{index_dir}'...")
        indexed_count = index_records(ix, new_articles)
        ix = ix.refresh()

        # Extract and index image subdocuments from new articles
        try:
            session = requests.Session()
            session.headers.update(HTTP_HEADERS)
            extracted_subdocs: list[dict[str, str]] = []
            for art in new_articles[:20]:
                u = art.get("url")
                if not u:
                    continue
                try:
                    r = session.get(u, timeout=5)
                    if r.status_code == 200:
                        sub = extract_image_subdocuments(
                            html=r.text,
                            page_url=u,
                            article_title=art.get("title", ""),
                            published_date=art.get("published_date", ""),
                        )
                        extracted_subdocs.extend(sub)
                except Exception:
                    pass

            if extracted_subdocs:
                img_data_path = Path(data_dir) / "images_dataset.json"
                save_image_subdocuments(extracted_subdocs, data_path=img_data_path)
                ix_img = get_or_create_image_index(
                    index_dir=image_index_dir,
                    data_file=img_data_path,
                )
                new_images_count = index_image_subdocuments(ix_img, extracted_subdocs)
                ix_img.refresh()
                logger.info(f"Indexed {new_images_count} new image subdocuments into '{image_index_dir}'.")
        except Exception as e:
            logger.warning(f"Error during image subdocument extraction: {e}")
    else:
        logger.info("No new articles discovered during this revisit.")

    elapsed = time.time() - start_time
    total_docs = ix.doc_count()

    summary = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "vnexpress_new": len(vne_articles),
        "baomoi_new": len(bm_articles),
        "total_new": len(new_articles),
        "indexed_count": indexed_count,
        "indexed_images": new_images_count,
        "total_docs": total_docs,
        "elapsed_seconds": round(elapsed, 2),
        "status": "Success",
    }
    save_crawler_status(summary, data_dir=data_dir)
    logger.info(
        f"--- Revisit Finished in {elapsed:.2f}s | "
        f"+{len(vne_articles)} VnExpress, +{len(bm_articles)} BaoMoi, +{new_images_count} Images | "
        f"Total indexed docs: {total_docs} ---"
    )
    return summary


def run_crawler_loop(
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    max_per_site: int = DEFAULT_MAX_NEW_POSTS_PER_SITE,
    data_dir: str | Path = "data",
    index_dir: str | Path = "indexdir",
    image_index_dir: str | Path = "image_indexdir",
    stop_event: threading.Event | None = None,
    run_once: bool = False,
) -> None:
    """Continuously runs the crawling revisit cycle every interval_seconds (default: 15 min)."""
    logger.info(
        f"Starting Crawling Loop: Revisit every {interval_seconds}s "
        f"({interval_seconds / 60:.1f} min), max {max_per_site} new posts/site."
    )

    # In-memory tracking across loop iterations
    seen_urls = get_known_urls(data_dir=data_dir, index_dir=index_dir)

    cycle_count = 0
    while True:
        cycle_count += 1
        logger.info(f"Crawling Cycle #{cycle_count} commencing...")
        try:
            crawl_and_index_revisit(
                index_dir=index_dir,
                data_dir=data_dir,
                image_index_dir=image_index_dir,
                max_per_site=max_per_site,
                seen_urls=seen_urls,
            )
        except Exception as err:
            logger.error(f"Error occurred during crawling cycle #{cycle_count}: {err}", exc_info=True)

        if run_once:
            logger.info("Run-once flag provided. Exiting crawling loop.")
            break

        logger.info(
            f"Cycle #{cycle_count} complete. Waiting {interval_seconds}s (15 min) until next revisit..."
        )

        if stop_event is not None:
            # Check stop_event periodically every second so shutdown is responsive
            if stop_event.wait(timeout=interval_seconds):
                logger.info("Crawler loop received stop signal. Terminating loop gracefully.")
                break
        else:
            time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="News Crawler Loop for VnExpress & BaoMoi"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Revisit interval in seconds (default: 900 = 15 minutes)",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=DEFAULT_MAX_NEW_POSTS_PER_SITE,
        help="Max new posts to crawl per website per revisit (default: 50)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single revisit cycle and exit immediately",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Path to data directory (default: 'data')",
    )
    parser.add_argument(
        "--index-dir",
        type=str,
        default="indexdir",
        help="Path to Whoosh article index directory (default: 'indexdir')",
    )
    parser.add_argument(
        "--image-index-dir",
        type=str,
        default="image_indexdir",
        help="Path to Whoosh image index directory (default: 'image_indexdir')",
    )

    args = parser.parse_args()
    run_crawler_loop(
        interval_seconds=args.interval,
        max_per_site=args.max_posts,
        data_dir=args.data_dir,
        index_dir=args.index_dir,
        image_index_dir=args.image_index_dir,
        run_once=args.once,
    )


if __name__ == "__main__":
    main()
