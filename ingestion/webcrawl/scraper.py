#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import sqlite3
import json
import re
import logging
import time
import random
import argparse
from urllib.parse import urljoin, urlparse
from .strategies import ProcessorFactory, SentenceSplitterFactory

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.129 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.129 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.129 Safari/537.36 Edg/122.0.2365.92"
]

def make_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,gu;q=0.8",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive"
    }

# Global stats
stats = {
    "new_links": 0,
    "skipped_links": 0,
    "skipped_already": 0,
    "skipped_excluded": 0,
    "skipped_depth": 0,
    "sentences": 0,
    "failed_links": 0,
    "discovered": 0
}
exclude_patterns = []
dry_run = False
discovered_urls = set()

# Stop condition variables
max_pages = 50
min_sentences = 1
max_total_links = 200


def stop_condition():
    if stats["new_links"] >= max_pages and stats["sentences"] >= min_sentences:
        return True
    if stats["new_links"] + stats["skipped_links"] >= max_total_links:
        logging.warning("Reached max_total_links hard stop.")
        return True
    return False


def is_excluded(url):
    for pat in exclude_patterns:
        if re.search(pat, url, re.IGNORECASE):
            return True
    return False


def url_already_scraped(conn, url):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM links WHERE url=? LIMIT 1", (url,))
    return cur.fetchone() is not None


def insert_link(conn, url):
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO links(url) VALUES (?)", (url,))
    conn.commit()
    cur.execute("SELECT id FROM links WHERE url=? LIMIT 1", (url,))
    return cur.fetchone()[0]


def insert_sentence(conn, link_id, sentence, status_override=None):
    cur = conn.cursor()
    status = status_override if status_override else 'new'
    cur.execute("INSERT INTO staging_sentences(link_id, sentence, status) VALUES (?, ?, ?)",
                (link_id, sentence, status))


def scrape_page(url, conn, depth, max_depth, visited, unicode_flag, delay, processors, is_root=False, splitter=None):
    global stats, dry_run, discovered_urls

    # 🚨 DRY RUN MODE
    if dry_run:
        if url in discovered_urls:
            return
        discovered_urls.add(url)

        logging.info(f"[DRY-RUN] Would visit: {url}")
        with open("urls_discovered.txt", "a", encoding="utf-8") as f:
            f.write(url + "\n")

        if depth < max_depth:
            try:
                r = requests.get(url, headers=make_headers(), timeout=15)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    next_url = urljoin(url, a["href"])
                    if urlparse(next_url).netloc != urlparse(url).netloc:
                        continue
                    if is_excluded(next_url):
                        logging.debug(f"[DRY-RUN] Skipping excluded: {next_url}")
                    scrape_page(next_url, None, depth+1, max_depth, visited, unicode_flag, delay, [])
            except Exception as e:
                logging.warning(f"[DRY-RUN] Failed to fetch links from {url}: {e}")
        return

    # 🚨 NORMAL MODE
    if stop_condition():
        return
    if url in visited:
        return
    visited.add(url)

    logging.info(f"Visiting: {url} (depth={depth})")
    try:
        time.sleep(random.uniform(0, delay))
        r = requests.get(url, headers=make_headers(), timeout=15)
        r.raise_for_status()
    except Exception as e:
        logging.error(f"Failed: {url} ({e})")
        stats["failed_links"] += 1
        return

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Process sentences only if not excluded or already scraped
    if not is_root and not url_already_scraped(conn, url) and not is_excluded(url):
        sentences = splitter(text)
        inserted = 0
        metadata = {"is_root": is_root, "url": url}
        for s in sentences:
            status_override = None
            for p in processors:
                result = p.process(s, metadata=metadata)
                if not result:
                    s = None
                    break
                if isinstance(result, tuple):
                    s, st = result
                    if not s:
                        s = None
                        break
                    if st:
                        status_override = st
                else:
                    s = result
            if s:
                if unicode_flag:
                    s = s.encode("unicode_escape").decode("utf-8")
                try:
                    link_id = insert_link(conn, url)
                    conn.commit()
                    insert_sentence(conn, link_id, s, status_override)
                    conn.commit()
                    inserted += 1
                    stats["sentences"] += 1
                except Exception as e:
                    logging.error(f"Failed inserting sentence: {e}")
        logging.info(f"{url} → {inserted} sentences inserted (Total: {stats['sentences']})")
        stats["new_links"] += 1
    else:
        if is_excluded(url):
            stats["skipped_links"] += 1
            stats["skipped_excluded"] += 1
        elif url_already_scraped(conn, url):
            stats["skipped_links"] += 1
            stats["skipped_already"] += 1

    # Recurse into children regardless, unless depth exceeded
    if depth < max_depth:
        for a in soup.find_all("a", href=True):
            next_url = urljoin(url, a["href"])
            if urlparse(next_url).netloc != urlparse(url).netloc:
                continue
            stats["discovered"] += 1
            if depth + 1 > max_depth:
                logging.info(f"Skipping URL at depth={depth+1} beyond max_depth={max_depth}: {next_url}")
                stats["skipped_links"] += 1
                stats["skipped_depth"] += 1
                continue
            scrape_page(next_url, conn, depth+1, max_depth, visited, unicode_flag, delay, processors, splitter=splitter)


def init_db(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staging_sentences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id INTEGER,
            sentence TEXT,
            status TEXT DEFAULT 'new',
            FOREIGN KEY(link_id) REFERENCES links(id)
        )
    """)
    conn.commit()


def main():
    global exclude_patterns, max_pages, min_sentences, max_total_links, dry_run

    parser = argparse.ArgumentParser(description="News Scraper")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    parser.add_argument("--dry-run", action="store_true", help="Exploratory dry-run: only print/save URLs, no DB")
    args = parser.parse_args()

    dry_run = args.dry_run

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    db_file = config["db_file"]
    base_url = config["base_url"]
    depth = config.get("depth", 1)
    delay = config.get("delay", 5)
    unicode_flag = config.get("unicode", False)
    exclude_patterns = config.get("exclude_patterns", [])

    tokenizer_conf = config.get("tokenizer", {"type": "regex", "lang": "gu"})
    splitter = SentenceSplitterFactory.build(tokenizer_conf)

    max_pages = config.get("max_pages", 50)
    min_sentences = config.get("min_sentences", 1)
    max_total_links = config.get("max_total_links", 200)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()]
    )

    logging.info(f"Starting crawler with config: {args.config}")
    logging.info(f"Config: max_pages={max_pages}, min_sentences={min_sentences}, max_total_links={max_total_links}, dry_run={dry_run}")

    if dry_run:
        open("urls_discovered.txt", "w").close()
        processors = []
        conn = None
    else:
        conn = sqlite3.connect(db_file)
        init_db(conn)
        processors = ProcessorFactory.build_processors(config.get("processors", {}), conn)
        logging.info(f"Enabled processors: {[p.__class__.__name__ for p in processors]}")

    visited = set()
    scrape_page(base_url, conn, 0, depth, visited, unicode_flag, delay, processors, is_root=True, splitter=splitter)

    logging.info("========== SUMMARY ==========")
    logging.info(f"New links visited : {stats['new_links']}")
    logging.info(f"Skipped links     : {stats['skipped_links']}")
    logging.info(f"   - Already scraped   : {stats['skipped_already']}")
    logging.info(f"   - Excluded by pattern: {stats['skipped_excluded']}")
    logging.info(f"   - Depth limit reached: {stats['skipped_depth']}")
    logging.info(f"Sentences inserted: {stats['sentences']}")
    logging.info(f"Failed links      : {stats['failed_links']}")
    logging.info(f"Total links discovered: {stats['discovered']}")
    logging.info("=============================")

    if stats["skipped_depth"] > 0:
        logging.warning("Some links were skipped due to depth limit — consider increasing depth.")
    elif stats["new_links"] == 0 and stats["sentences"] == 0:
        logging.warning("No new content found — site may not have updated or all content is already scraped.")

    if conn:
        conn.close()


if __name__ == "__main__":
    main()
