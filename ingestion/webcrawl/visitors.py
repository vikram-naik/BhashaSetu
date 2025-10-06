import logging
import random
import time
import re
import requests
import sqlite3
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from .repositories import LinkRepository, SentenceRepository, init_db
from .strategies import SentenceSplitterFactory, ProcessorFactory, ProcessorResult

# ---------------------------------------------------------
# Helper — polite headers
# ---------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0"
]

def make_headers():
    """Generate polite randomized request headers."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,gu;q=0.8",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive"
    }


# ---------------------------------------------------------
# Base Visitor Interface
# ---------------------------------------------------------
class Visitor:
    def initialize(self, config): pass
    def on_crawl_start(self, context): pass
    def on_crawl_end(self, context): pass
    def on_page_start(self, context): pass
    def on_page_process(self, context): pass
    def on_page_end(self, context): pass
    def on_link_discovered(self, context, link): pass


# ---------------------------------------------------------
# Stats Visitor
# ---------------------------------------------------------
class StatsVisitor(Visitor):
    def on_crawl_start(self, context):
        logging.info(f"[Crawl] Starting crawl: {context.config.get('base_url')}")

    def on_crawl_end(self, context):
        elapsed = time.time() - context.start_time
        logging.info("========== SUMMARY ==========")
        for k, v in context.stats.items():
            logging.info(f"{k:20}: {v}")
        logging.info(f"Elapsed: {elapsed:.2f}s")
        logging.info("=============================")


# ---------------------------------------------------------
# URL Tracker Visitor
# ---------------------------------------------------------
class URLTrackerVisitor(Visitor):
    def on_page_start(self, context):
        url = context.page.url
        if url in context.visited:
            context.page.flags["duplicate"] = True
            context.log("Already visited — marking duplicate")
        else:
            context.visited.add(url)
            context.log("New URL registered")


# ---------------------------------------------------------
# Exclusion Visitor
# ---------------------------------------------------------
class ExclusionVisitor(Visitor):
    def on_page_start(self, context):
        url = context.page.url
        for pat in context.config.get("exclude_patterns", []):
            if re.search(pat, url, re.IGNORECASE):
                context.page.flags["excluded"] = True
                context.log(f"Excluded by pattern: {pat}")
                return


# ---------------------------------------------------------
# Fetcher Visitor
# ---------------------------------------------------------
class FetcherVisitor(Visitor):
    """Handles polite HTTP fetching of pages, logs root differently."""

    def on_page_process(self, context):
        page = context.page
        if page.should_skip():
            context.log("[Fetcher] Skipping due to skip_processing or other flag")
            return

        root_prefix = "[ROOT] " if page.is_root else ""
        delay = random.uniform(0, context.config.get("delay", 5))
        context.log(f"{root_prefix}[Delay] Waiting {delay:.2f}s before fetching")
        time.sleep(delay)

        try:
            r = requests.get(page.url, headers=make_headers(), timeout=15)
            r.raise_for_status()
            page.text = r.text
            kb = len(r.text) / 1024
            context.log(f"{root_prefix}[Fetcher] {kb:.1f} KB fetched successfully")
        except Exception as e:
            page.flags["failed"] = True
            context.stats["errors"] += 1
            context.log(f"{root_prefix}[Fetcher] Failed: {e}")


# ---------------------------------------------------------
# Parser Visitor
# ---------------------------------------------------------
class ParserVisitor(Visitor):
    def on_page_process(self, context):
        page = context.page
        if page.should_skip() or not getattr(page, "text", None):
            context.log("[Parser] Skipping due to skip_processing or missing text")
            return

        soup = BeautifulSoup(page.text, "html.parser")
        page.text_clean = soup.get_text(" ", strip=True)
        page.links = [
            a["href"] for a in soup.find_all("a", href=True)
            if urlparse(a["href"]).scheme in ("http", "https") or a["href"].startswith("/")
        ]
        root_prefix = "[ROOT] " if page.is_root else ""
        context.log(f"{root_prefix}[Parser] Extracted {len(page.links)} links")


# ---------------------------------------------------------
# Sentence Processor Visitor
# ---------------------------------------------------------
class SentenceProcessorVisitor(Visitor):
    def initialize(self, config):
        self.splitter = SentenceSplitterFactory.build(config.get("tokenizer", {"type": "regex"}))
        self.processors = ProcessorFactory.build_processors(config.get("processors", {}))
        logging.info("[SentenceProcessorVisitor] Initialized")

    def on_page_process(self, context):
        page = context.page
        if page.should_skip() or not getattr(page, "text_clean", None):
            context.log("[SentenceProcessor] Skipping due to skip_processing or missing clean text")
            return

        results: list[ProcessorResult] = []
        metadata = {"url": page.url, "is_root": page.is_root}   # ✅ root-awareness

        for s in self.splitter(page.text_clean):
            sentence_status = None
            current_text = s
            rejected = False

            for p in self.processors:
                result = p.process(current_text, metadata=metadata)
                if not isinstance(result, ProcessorResult):
                    raise TypeError(f"{p.__class__.__name__} must return ProcessorResult, got {type(result)}")

                if result.reject:
                    rejected = True
                    break

                current_text = result.text
                if result.status:
                    sentence_status = result.status

                if result.status == "rejected":
                    break    

            if not rejected and current_text:
                results.append(ProcessorResult(text=current_text, status=sentence_status))

        page.sentences = [r.text for r in results]
        page.sentence_statuses = [r.status or "new" for r in results]
        context.stats["sentences"] += len(page.sentences)
        context.log(f"[SentenceProcessor] {len(page.sentences)} sentences processed")


# ---------------------------------------------------------
# DB Visitor
# ---------------------------------------------------------
class DBVisitor(Visitor):
    """Handles all database interaction (self-contained)."""

    def initialize(self, config):
        db_path = config.get("db_file", "crawler.db")
        self.conn = sqlite3.connect(db_path)
        init_db(self.conn)
        self.links = LinkRepository(self.conn)
        self.sentences = SentenceRepository(self.conn)
        logging.info(f"[DBVisitor] Connected and initialized DB: {db_path}")

    def on_page_start(self, context):
        """Early skip if this URL already exists in the DB (except root)."""
        page = context.page

        # ✅ Allow reprocessing of root page (for fresh links)
        if page.is_root:
            page.flags["already_in_db"] = False
            page.flags["skip_processing"] = False
            context.log("[DBVisitor] Root page detected — always process for link discovery")
            return

        # Regular deduplication for non-root URLs
        if self._url_exists(page.url):
            page.flags["already_in_db"] = True
            page.flags["skip_processing"] = True
            context.log(f"[DBVisitor] URL already present in DB — skipping downstream processing")
        else:
            page.flags["already_in_db"] = False
            page.flags["skip_processing"] = False

    def on_page_end(self, context):
        page = context.page

        # ✅ Root page may not have sentences — don’t skip DB check logic
        if page.is_root:
            context.log("[DBVisitor] Root page processed — skipping DB insert")
            return

        if page.flags.get("already_in_db"):
            context.log("[DBVisitor] Skipped DB insert — URL already exists")
            return

        if page.should_skip() or not getattr(page, "sentences", []):
            return

        try:
            link_id = self.links.insert(page.url)
            for s, st in zip(page.sentences, page.sentence_statuses):
                self.sentences.insert(link_id, s, st)
            self.conn.commit()
            context.log(f"[DBVisitor] Inserted {len(page.sentences)} sentences with statuses")
        except Exception as e:
            context.stats["errors"] += 1
            context.log(f"[DBVisitor] Insert failed: {e}")

    def _url_exists(self, url: str) -> bool:
        """Check if the URL already exists in DB."""
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM links WHERE url=? LIMIT 1", (url,))
        return cur.fetchone() is not None

    def on_crawl_end(self, context):
        if self.conn:
            try:
                self.conn.close()
                logging.info("[DBVisitor] Closed DB connection")
            except Exception as e:
                logging.error(f"[DBVisitor] Failed to close DB connection: {e}")
