import random
import time
import re
import requests
import sqlite3
import functools
import logging
import hashlib
import unicodedata

from bs4 import BeautifulSoup
from urllib.parse import urlparse
from .repositories import (
    DomainRepository, LinkRepository, SentenceDomainRepository,
    SentenceRepository, init_db
)
from .strategies import SentenceSplitterFactory, ProcessorFactory, ProcessorResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# Implicit attributes that every Page has by design
# ---------------------------------------------------------
IMPLICIT_PAGE_ATTRS = {
    "page.url",
    "page.flags",
    "page.is_root",
    "page.depth",
    "page.text",
}


# ---------------------------------------------------------
# Helper – polite randomized headers
# ---------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

def make_headers():
    """Generate polite randomized request headers."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,gu;q=0.8",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
    }


# ---------------------------------------------------------
# Aspect: automatic validation decorator
# ---------------------------------------------------------
def auto_validate(func):
    """Aspect to run validate_page_state(page) automatically before visitor logic."""
    @functools.wraps(func)
    def wrapper(self, context, *args, **kwargs):
        if getattr(self, "skip_auto_validate", False):
            return func(self, context, *args, **kwargs)

        page = getattr(context, "page", None)
        if page is not None and hasattr(self, "validate_page_state"):
            try:
                self.validate_page_state(page)
            except RuntimeError as e:
                raise RuntimeError(
                    f"[{self.__class__.__name__}.{func.__name__}] Validation failed: {e}"
                ) from e
        return func(self, context, *args, **kwargs)
    return wrapper


class VisitorMeta(type):
    """Metaclass to auto-wrap lifecycle methods with validation aspects."""
    def __new__(mcls, name, bases, attrs):
        for method_name in [
            "on_page_start",
            "on_page_process",
            "on_page_end",
            "on_link_discovered",
        ]:
            if method_name in attrs:
                attrs[method_name] = auto_validate(attrs[method_name])
        return super().__new__(mcls, name, bases, attrs)


# ---------------------------------------------------------
# Base Visitor Interface
# ---------------------------------------------------------
class Visitor(metaclass=VisitorMeta):
    consumes: list[str] = []
    produces: list[str] = []
    skip_auto_validate: bool = False  # opt-out for meta/system visitors

    def initialize(self, config): pass
    def on_crawl_start(self, context): pass
    def on_crawl_end(self, context): pass
    def on_page_start(self, context): pass
    def on_page_process(self, context): pass
    def on_page_end(self, context): pass
    def on_link_discovered(self, context, link): pass

    # ---- Runtime validation ----
    def validate_page_state(self, page):
        missing = [a for a in getattr(self, "consumes", []) if not self._has_attr(page, a)]
        if missing:
            raise RuntimeError(
                f"Missing required attributes on Page: {missing}"
            )

    @staticmethod
    def _has_attr(page, dotted_attr):
        """Support dot notation and nested dicts (e.g. page.flags.excluded)"""
        parts = dotted_attr.split(".")
        obj = page
        for p in parts[1:]:  # skip 'page'
            if isinstance(obj, dict):
                if p not in obj:
                    return False
                obj = obj[p]
            elif hasattr(obj, p):
                obj = getattr(obj, p)
            else:
                return False
        return True


# ---------------------------------------------------------
# Visitor Chain Validator
# ---------------------------------------------------------
class VisitorChainValidator(Visitor):
    skip_auto_validate = True
    consumes = []
    produces = []

    def on_crawl_start(self, context):
        visitors = getattr(context, "visitors", [])
        visitor_classes = [v.__class__.__name__ for v in visitors]
        logging.info(f"[Validator] Validating visitor chain: {visitor_classes}")

        produced = set(IMPLICIT_PAGE_ATTRS)
        for idx, v in enumerate(visitors):
            v_name = v.__class__.__name__
            consumes = getattr(v, "consumes", [])
            produces = getattr(v, "produces", [])

            missing = [
                c for c in consumes
                if c not in produced and c not in IMPLICIT_PAGE_ATTRS
            ]
            if missing:
                raise RuntimeError(
                    f"[Validator] {v_name} requires {missing}, "
                    f"but they are not produced by any prior visitor."
                )

            for p in produces:
                produced.add(p)

        logging.info(
            f"[Validator] Chain validated successfully — total produced: {len(produced)}"
        )


# ---------------------------------------------------------
# Stats Visitor
# ---------------------------------------------------------
class StatsVisitor(Visitor):
    skip_auto_validate = True

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
    consumes = ["page.url"]
    produces = ["page.flags.visited"]

    def on_page_start(self, context):
        page = context.page
        if url := getattr(page, "url", None):
            if url in context.visited:
                page.flags["duplicate"] = True
                context.log("Already visited — marking duplicate")
            else:
                context.visited.add(url)
                page.flags["visited"] = True
                context.log("New URL registered")


# ---------------------------------------------------------
# Exclusion Visitor
# ---------------------------------------------------------
class ExclusionVisitor(Visitor):
    consumes = ["page.url"]
    produces = ["page.flags.excluded"]

    def on_page_start(self, context):
        page = context.page
        url = page.url
        for pat in context.config.get("exclude_patterns", []):
            if re.search(pat, url, re.IGNORECASE):
                page.flags["excluded"] = True
                context.log(f"[ExclusionVisitor] Excluded by pattern: {pat}")
                return


# ---------------------------------------------------------
# Fetcher Visitor
# ---------------------------------------------------------
class FetcherVisitor(Visitor):
    consumes = ["page.url", "page.flags"]
    produces = ["page.text"]

    def on_page_process(self, context):
        page = context.page
        if page.should_skip():
            context.log("[Fetcher] Skipping due to flags", level=logging.DEBUG)
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
    consumes = ["page.text"]
    produces = ["page.text_clean", "page.links"]

    def on_page_process(self, context):
        page = context.page
        if page.should_skip() or not getattr(page, "text", None):
            context.log("[Parser] Skipping due to missing text", level=logging.DEBUG)
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
    consumes = ["page.text_clean"]
    produces = ["page.processed_results", "page.sentences", "page.sentence_statuses"]

    def initialize(self, config):
        self.splitter = SentenceSplitterFactory.build(config.get("tokenizer", {"type": "regex"}))
        self.processors = ProcessorFactory.build_processors(config.get("processors", {}))
        logging.info("[SentenceProcessorVisitor] Initialized")

    def on_page_process(self, context):
        page = context.page
        if page.should_skip() or not getattr(page, "text_clean", None):
            context.log("[SentenceProcessor] Skipping — no clean text", level=logging.DEBUG)
            page.processed_results = []
            return

        results: list[ProcessorResult] = []
        metadata = {"url": page.url, "is_root": page.is_root}

        for s in self.splitter(page.text_clean):
            sentence_status = None
            current_text = s
            rejected = False
            domain_meta = {}

            for p in self.processors:
                result = p.process(current_text, metadata=metadata)
                if not isinstance(result, ProcessorResult):
                    raise TypeError(f"{p.__class__.__name__} must return ProcessorResult")

                if result.reject:
                    rejected = True
                    break

                current_text = result.text
                if result.status:
                    sentence_status = result.status

                if result.metadata:
                    domain_meta.update(result.metadata)

                # ✅ Stop if processor marks sentence rejected
                if result.status == "rejected":
                    break

            if not rejected and current_text:
                pr = ProcessorResult(
                    text=current_text,
                    status=sentence_status or "new",
                    metadata=domain_meta or {}
                )
                results.append(pr)

        page.processed_results = results
        page.sentences = [r.text for r in results]
        page.sentence_statuses = [r.status for r in results]
        context.stats["sentences"] += len(results)
        context.log(f"[SentenceProcessor] {len(results)} sentences processed")


# ---------------------------------------------------------
# DB Visitor
# ---------------------------------------------------------

class DBVisitor(Visitor):
    consumes = ["page.url", "page.flags"]
    produces = ["page.flags.already_in_db"]

    def initialize(self, config):
        db_path = config.get("db_file", "crawler.db")
        self.conn = sqlite3.connect(db_path)
        init_db(self.conn)
        self.links = LinkRepository(self.conn)
        self.sentences = SentenceRepository(self.conn)
        self._table_has_cache = {}
        logger.info(f"[DBVisitor] Connected and initialized DB: {db_path}")

    # ---------- helpers ----------
    def _table_has_column(self, table: str, column: str) -> bool:
        key = (table, column)
        if key in self._table_has_cache:
            return self._table_has_cache[key]
        cur = self.conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        exists = column in cols
        self._table_has_cache[key] = exists
        return exists

    @staticmethod
    def _normalize_text(text: str) -> str:
        t = unicodedata.normalize("NFKC", text or "")
        t = re.sub(r"\s+", " ", t.strip().lower())
        return t

    @classmethod
    def _hash_text(cls, text: str) -> str:
        norm = cls._normalize_text(text)
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()

    def _insert_sentence_row(self, link_id: int, sentence: str, status: str = "new",
                             hash_val: str = None, duplicate_of: int = None) -> int:
        cur = self.conn.cursor()
        cols = ["link_id", "sentence", "status"]
        vals = [link_id, sentence, status]

        if self._table_has_column("staging_sentences", "hash") and hash_val is not None:
            cols.append("hash"); vals.append(hash_val)
        if self._table_has_column("staging_sentences", "duplicate_of") and duplicate_of is not None:
            cols.append("duplicate_of"); vals.append(duplicate_of)

        placeholders = ",".join(["?"] * len(cols))
        sql = f"INSERT INTO staging_sentences ({','.join(cols)}) VALUES ({placeholders})"
        cur.execute(sql, tuple(vals))
        self.conn.commit()
        return cur.lastrowid

    # ---------- lifecycle ----------
    def on_page_start(self, context):
        page = context.page
        # root always processed to discover links
        if page.is_root:
            page.flags["already_in_db"] = False
            page.flags["skip_processing"] = False
            context.log("[DBVisitor] Root page detected — always process for link discovery")
            return

        if self._url_exists(page.url):
            page.flags["already_in_db"] = True
            page.flags["skip_processing"] = True
            context.log("[DBVisitor] URL already present in DB — skipping downstream processing")
        else:
            page.flags["already_in_db"] = False
            page.flags["skip_processing"] = False

    def on_page_end(self, context):
        page = context.page

        # Protocol: SentenceProcessorVisitor must have run and attached processed_results
        if not hasattr(page, "processed_results"):
            raise RuntimeError(
                "[DBVisitor] Missing 'processed_results' on Page — ensure SentenceProcessorVisitor ran before DBVisitor."
            )

        # Root page: we still want to discover links, but do not insert sentences from root.
        if page.is_root:
            context.log("[DBVisitor] Root page processed — skipping DB insert of sentences")
            return

        # If URL already in DB we skip insertion (we still want to farm new links from page)
        if page.flags.get("already_in_db"):
            context.log("[DBVisitor] Skipping DB insert — URL already exists")
            return

        if page.should_skip() or not getattr(page, "processed_results", []):
            return

        try:
            link_id = self.links.insert(page.url)
            domain_repo = DomainRepository(self.conn)
            sentence_domain_repo = SentenceDomainRepository(self.conn)

            inserted = 0
            dup_count = 0

            use_hash = self._table_has_column("staging_sentences", "hash")

            for r in getattr(page, "processed_results", []):
                s = (r.text or "").strip()
                if not s:
                    continue
                st = r.status or "new"

                # ---------- duplicate detection ----------
                if use_hash:
                    h = self._hash_text(s)
                    cur = self.conn.cursor()
                    cur.execute("SELECT id FROM staging_sentences WHERE hash=? LIMIT 1", (h,))
                    row = cur.fetchone()
                    if row:
                        # Found an earlier identical sentence (normalized->hash match)
                        orig_id = row[0]
                        # Insert a record marked as duplicate for audit, pointing to original.
                        new_id = self._insert_sentence_row(link_id, s, status="duplicate",
                                                           hash_val=h, duplicate_of=orig_id)
                        dup_count += 1
                        context.log(f"[DBVisitor] Duplicate (hash) -> sid={new_id}, orig={orig_id}", level=logging.DEBUG)
                        continue
                    else:
                        # not a duplicate -> insert with hash
                        new_id = self._insert_sentence_row(link_id, s, status=st, hash_val=h)
                else:
                    # fallback: exact-string check (backwards compatible)
                    cur = self.conn.cursor()
                    cur.execute("SELECT id FROM staging_sentences WHERE sentence=? LIMIT 1", (s,))
                    row = cur.fetchone()
                    if row:
                        orig_id = row[0]
                        new_id = self._insert_sentence_row(link_id, s, status="duplicate")
                        dup_count += 1
                        context.log(f"[DBVisitor] Duplicate (exact) -> sid={new_id}, orig={orig_id}", level=logging.DEBUG)
                        continue
                    else:
                        new_id = self._insert_sentence_row(link_id, s, status=st)

                # ---------- domain mapping (only for non-duplicate inserts) ----------
                meta = getattr(r, "metadata", {}) or {}
                domain_code = meta.get("domain_code", "misc")
                domain_name = meta.get("domain_name", "Miscellaneous")
                domain_id = domain_repo.get_or_create(domain_code, domain_name)
                sentence_domain_repo.insert(
                    new_id,
                    domain_id,
                    confidence=meta.get("confidence"),
                    source=meta.get("source", "rule_based")
                )

                inserted += 1

            self.conn.commit()
            context.log(f"[DBVisitor] Inserted={inserted}, duplicates_marked={dup_count}")
        except Exception as e:
            context.stats["errors"] += 1
            context.log(f"[DBVisitor] Insert failed: {e}", level=logging.ERROR)

    def _url_exists(self, url: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM links WHERE url=? LIMIT 1", (url,))
        return cur.fetchone() is not None

    def on_crawl_end(self, context):
        if getattr(self, "conn", None):
            try:
                self.conn.close()
                logging.info("[DBVisitor] Closed DB connection")
            except Exception as e:
                logging.error(f"[DBVisitor] DB close error: {e}")
