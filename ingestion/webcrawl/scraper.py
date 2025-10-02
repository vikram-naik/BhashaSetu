import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import sqlite3
import re
import argparse
import time
import random
import logging
import json
from indicnlp.tokenize import sentence_tokenize
from .strategies import ProcessorFactory  # relative import for webcrawl package

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,gu;q=0.8",
}

stats = {"new_links": 0, "skipped_links": 0, "sentences": 0, "failed": 0}
exclude_patterns = []
lang = "gu"
processors = []
count_skipped = False
max_pages = 0
min_sentences = 1

def init_db(db_file):
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS links (
        id INTEGER PRIMARY KEY,
        url TEXT UNIQUE,
        scraped_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS staging_sentences (
        id INTEGER PRIMARY KEY,
        link_id INTEGER,
        sentence TEXT,
        FOREIGN KEY(link_id) REFERENCES links(id)
    )""")
    conn.commit()
    return conn

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def split_sentences(text):
    return sentence_tokenize.sentence_split(text, lang)

def is_excluded(url):
    for pat in exclude_patterns:
        if re.search(pat, url, re.IGNORECASE):
            return True
    return False

def url_already_scraped(conn, url):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM links WHERE url=? LIMIT 1", (url,))
    return cur.fetchone() is not None

def process_sentence(sentence, processors):
    s = sentence.strip()
    for p in processors:
        if s is None:
            return None
        s = p.process(s)
    return s

def stop_condition():
    # normal stop: enough pages AND sentences
    if stats["new_links"] >= max_pages and stats["sentences"] >= min_sentences:
        return True
    # hard stop: touched too many links overall
    if stats["new_links"] + stats["skipped_links"] >= max_total_links:
        logging.warning("Reached max_total_links hard stop.")
        return True
    return False

def scrape_page(url, conn, depth, max_depth, visited, unicode_flag, delay, is_root=False):
    global stats, count_skipped

    if stop_condition():
        return
    if url in visited:
        return
    visited.add(url)

    # only skip non-root URLs if already in DB
    if not is_root and url_already_scraped(conn, url):
        logging.info(f"Skipping already-scraped URL: {url}")
        stats["skipped_links"] += 1
        return

    logging.info(f"Visiting: {url} (depth={depth})")

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to fetch {url} ({e})", exc_info=True)
        stats["failed"] += 1
        return

    try:
        soup = BeautifulSoup(r.text, "html.parser")
        text_blocks = [p.get_text() for p in soup.find_all("p")]
        text = clean_text(" ".join(text_blocks))

        inserted = 0
        if text:
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO links(url) VALUES (?)", (url,))
            link_id = cur.lastrowid or cur.execute("SELECT id FROM links WHERE url=?", (url,)).fetchone()[0]

            raw_sentences = split_sentences(text)
            for raw in raw_sentences:
                s = process_sentence(raw, processors)
                if not s:
                    continue
                if unicode_flag:
                    s = s.encode('unicode_escape').decode('utf-8')
                cur.execute("INSERT INTO staging_sentences(link_id, sentence) VALUES (?, ?)", (link_id, s))
                inserted += 1
            conn.commit()

        stats["new_links"] += 1
        stats["sentences"] += inserted
        logging.info(f"{url} → {inserted} sentences inserted (Total: {stats['sentences']})")

    except Exception as e:
        logging.error(f"Error processing {url}: {e}", exc_info=True)
        return

    if delay > 0:
        time.sleep(random.uniform(0, delay))

    if depth < max_depth and not stop_condition():
        for a in soup.find_all("a", href=True):
            next_url = urljoin(url, a["href"])
            if urlparse(next_url).netloc != urlparse(url).netloc:
                continue
            if is_excluded(next_url):
                continue
            scrape_page(next_url, conn, depth+1, max_depth, visited, unicode_flag, delay)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gujarati News Scraper with Strategy + Factory")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(config.get("log_file", "scraper.log"), encoding="utf-8"),
            logging.StreamHandler()
        ]
    )

    exclude_patterns = config.get("exclude_patterns", [])
    lang = config.get("indic", {}).get("lang", "gu")
    count_skipped = config.get("count_skipped", False)
    max_pages = config.get("max_pages", 50)
    min_sentences = config.get("min_sentences", 1)
    max_total_links = config.get("max_total_links", 200)

    conn = init_db(config["db_file"])
    processors = ProcessorFactory.build_processors(config.get("processors", {}), conn)

    logging.info(f"Enabled processors: {[p.__class__.__name__ for p in processors]}")
    logging.info(f"Config: max_pages={max_pages}, min_sentences={min_sentences}, count_skipped={count_skipped}")

    try:
        scrape_page(
            config["base_url"], conn,
            0, config.get("depth", 1),
            set(),
            config.get("unicode", False),
            config.get("delay", 0),
            is_root=True
        )
    except Exception as e:
        logging.critical("Fatal error in scraping loop", exc_info=True)
    finally:
        conn.close()

    logging.info("========== SUMMARY ==========")
    logging.info(f"New links visited : {stats['new_links']}")
    logging.info(f"Skipped links     : {stats['skipped_links']}")
    logging.info(f"Sentences inserted: {stats['sentences']}")
    logging.info(f"Failed links      : {stats['failed']}")
    logging.info("=============================")
