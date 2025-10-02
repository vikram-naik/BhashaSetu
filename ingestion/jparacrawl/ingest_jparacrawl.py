#!/usr/bin/env python3
"""
ingestion/jparacrawl/ingest_jparacrawl.py

Features:
- Accepts archive (.zip, .tar.gz, .tgz, .tar) or plain text (.txt/.tsv).
- Parses JParaCrawl line format with 5 columns:
    source_domain_en \t source_domain_ja \t alignment_score \t en_text \t ja_text
  (but also tolerates other common OPUS layouts).
- Extracts LICENSE / CITATION / README from archive and stores in source.metadata.
- Creates domain, source, method, direction reference rows if missing.
- Batch inserts sentences and translation links; avoids duplicates.
- Prompts for Postgres password interactively if DB_PASS not set in env.
"""

from __future__ import annotations
import os
import zipfile
import tarfile
import argparse
import logging
import requests
import getpass
import json
from pathlib import Path
from typing import List, Tuple, Optional, Iterable, Dict

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# -------------------------
# Config (env-overridable)
# -------------------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "bhashasetu")
DB_USER = os.getenv("DB_USER", "bhasha_user")
DB_PASS = os.getenv("DB_PASS") or getpass.getpass("Postgres password: ")

# default download URL (only used when file missing and you want auto-download)
JPARA_URL = os.getenv(
    "JPARACRAWL_URL",
    "http://opus.nlpl.eu/download.php?f=JParaCrawl/v3.0/moses/en-ja.txt.zip",
)
DEFAULT_LOCAL = os.getenv("JPARACRAWL_FILE", "en-ja.txt")

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))

# canonical defaults (script will create if missing)
DEFAULT_DOMAIN_CODE = "web-crawl"
DEFAULT_DOMAIN_DESC = "Web-crawled parallel corpus (JParaCrawl / OPUS)"
DEFAULT_SOURCE_TYPE = "jparacrawl"
DEFAULT_SOURCE_NAME = "JParaCrawl (OPUS)"
DEFAULT_METHOD_NAME = "corpus"
DEFAULT_DIRECTION_CODE = "en2ja"

# -------------------------
# DB helpers
# -------------------------
def get_conn():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def next_uid(cur, table: str, uid_col: str) -> int:
    cur.execute(f"SELECT COALESCE(MAX({uid_col}), 0) + 1 FROM bhashasetu.{table}")
    return cur.fetchone()[0]


def get_language_uid(cur, code: str) -> int:
    cur.execute(
        "SELECT language_uid FROM bhashasetu.language WHERE code = %s AND is_active = TRUE ORDER BY version DESC LIMIT 1",
        (code,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Language code not found in database: {code} (seed languages first)")
    return row[0]


def get_or_create_domain(cur, code: str, description: str) -> int:
    cur.execute("SELECT domain_uid FROM bhashasetu.domain WHERE code = %s AND is_active = TRUE ORDER BY version DESC LIMIT 1", (code,))
    row = cur.fetchone()
    if row:
        return row[0]
    uid = next_uid(cur, "domain", "domain_uid")
    cur.execute(
        "INSERT INTO bhashasetu.domain (domain_uid, version, code, description, is_active) VALUES (%s, 1, %s, %s, TRUE)",
        (uid, code, description),
    )
    logging.info("Created domain %s (uid=%s)", code, uid)
    return uid


def get_or_create_method(cur, name: str, description: str = "", provider: str = "") -> int:
    cur.execute("SELECT method_uid FROM bhashasetu.method_lookup WHERE name = %s ORDER BY version DESC LIMIT 1", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    uid = next_uid(cur, "method_lookup", "method_uid")
    cur.execute(
        "INSERT INTO bhashasetu.method_lookup (method_uid, version, name, description, provider, is_active) VALUES (%s, 1, %s, %s, %s, TRUE)",
        (uid, name, description, provider),
    )
    logging.info("Created method %s (uid=%s)", name, uid)
    return uid


def get_or_create_direction(cur, code: str, source_lang_uid: int, target_lang_uid: int) -> int:
    cur.execute("SELECT direction_uid FROM bhashasetu.direction_lookup WHERE code = %s ORDER BY version DESC LIMIT 1", (code,))
    row = cur.fetchone()
    if row:
        return row[0]
    uid = next_uid(cur, "direction_lookup", "direction_uid")
    cur.execute(
        "INSERT INTO bhashasetu.direction_lookup (direction_uid, version, code, source_lang_uid, target_lang_uid, description, is_active) "
        "VALUES (%s, 1, %s, %s, %s, %s, TRUE)",
        (uid, code, source_lang_uid, target_lang_uid, f"{code} direction"),
    )
    logging.info("Created direction %s (uid=%s)", code, uid)
    return uid


def get_or_create_source(cur, typ: str, name: str, author: Optional[str] = None, url: Optional[str] = None, metadata: Optional[Dict] = None) -> int:
    # Try by name first (most stable)
    cur.execute("SELECT source_uid, metadata FROM bhashasetu.source WHERE name = %s ORDER BY version DESC LIMIT 1", (name,))
    row = cur.fetchone()
    if row:
        existing_uid, existing_meta = row[0], row[1] or {}
        if metadata:
            # merge metadata (new keys override)
            merged = {**existing_meta, **metadata}
            cur.execute("UPDATE bhashasetu.source SET metadata = %s WHERE source_uid = %s", (json.dumps(merged), existing_uid))
        return existing_uid

    uid = next_uid(cur, "source", "source_uid")
    cur.execute(
        "INSERT INTO bhashasetu.source (source_uid, version, type, name, author, url, metadata, is_active) "
        "VALUES (%s, 1, %s, %s, %s, %s, %s, TRUE)",
        (uid, typ, name, author, url, json.dumps(metadata or {})),
    )
    logging.info("Created source %s (uid=%s)", name, uid)
    return uid


# -------------------------
# Insert helpers
# -------------------------
def batch_insert_sentences(cur, texts: List[str], language_uid: int, source_uid: int, domain_uid: Optional[int]) -> Dict[str, int]:
    """
    Insert missing sentences and return mapping text -> id for all texts in the input list.
    """
    if not texts:
        return {}

    # 1) find existing sentences (language + any text in list)
    cur.execute("SELECT id, text FROM bhashasetu.sentence WHERE language_uid = %s AND text = ANY(%s)", (language_uid, texts))
    existing = {row[1]: row[0] for row in cur.fetchall()}

    # 2) insert missing
    missing = [t for t in texts if t not in existing]
    inserted = {}
    if missing:
        tuples = [(t, language_uid, source_uid, domain_uid) for t in missing]
        sql = "INSERT INTO bhashasetu.sentence (text, language_uid, source_uid, domain_uid) VALUES %s RETURNING id, text"
        execute_values(cur, sql, tuples)
        rows = cur.fetchall()
        for rid, txt in rows:
            inserted[txt] = rid

    # 3) merge and return
    mapping = existing.copy()
    mapping.update(inserted)
    return mapping


def insert_translation_if_not_exists(cur, src_id: int, tgt_id: int, direction_uid: int, method_uid: int):
    """
    Insert a translation row if not already present.
    Column names used: source_id, target_id, direction_uid, method_uid
    (Matches the schema used in this project.)
    """
    cur.execute(
        """
        INSERT INTO bhashasetu.translation (source_id, target_id, direction_uid, method_uid, is_synthetic, created_at)
        SELECT %s, %s, %s, %s, FALSE, NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM bhashasetu.translation WHERE source_id = %s AND target_id = %s AND direction_uid = %s
        )
        """,
        (src_id, tgt_id, direction_uid, method_uid, src_id, tgt_id, direction_uid),
    )


# -------------------------
# Parsing functions
# -------------------------
def parse_jparacrawl_line_columns(line: str) -> Optional[Tuple[str, str, Optional[float], Dict]]:
    """
    Parse a line with 5+ tab-separated columns:
    col0: source_domain_en
    col1: source_domain_ja
    col2: alignment_score (float)
    col3: en_text
    col4: ja_text
    Returns (en, ja, score_float_or_none, meta_dict)
    """
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 4:
        return None
    # Some variants may have many columns; en is near the end.
    # If we have >=5, use parts[3], parts[4]
    if len(parts) >= 5:
        try:
            score = float(parts[2]) if parts[2] != "" else None
        except Exception:
            score = None
        en = parts[3].strip()
        ja = parts[4].strip()
        meta = {"src_domain_en": parts[0], "src_domain_ja": parts[1], "alignment_score": score}
        return (en, ja, score, meta)
    # If exactly 4 columns (some variants), treat last two as en/ja
    if len(parts) == 4:
        en = parts[2].strip()
        ja = parts[3].strip()
        return (en, ja, None, {})
    # fallback
    return None


def parse_text_file_lines(path: str) -> Iterable[Tuple[str, str, Optional[float], Dict]]:
    logging.info("Parsing plain text file %s", path)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parsed = parse_jparacrawl_line_columns(line)
            if parsed:
                yield parsed


def parse_members(names: List[str], open_func) -> Iterable[Tuple[str, str, Optional[float], Dict]]:
    """
    Given archive member names and an opener function (zf.open or tf.extractfile),
    find the likely pairs file and yield (en, ja, score, meta).
    """
    # prefer files with 'en-ja' substring, else pick the largest file
    candidate = next((n for n in names if "en-ja" in n.lower()), None)
    if candidate is None:
        candidate = max(names, key=lambda n: len(n))
    logging.info("Parsing candidate file in archive: %s", candidate)

    with open_func(candidate) as fh:
        for raw in fh:
            try:
                line = raw.decode("utf-8", errors="replace")
            except Exception:
                try:
                    line = raw.read().decode("utf-8", errors="replace")
                except Exception:
                    continue
            parsed = parse_jparacrawl_line_columns(line)
            if parsed:
                yield parsed


def parse_archive_or_file(path: str) -> Iterable[Tuple[str, str, Optional[float], Dict]]:
    """
    Dispatch to zip/tar/plain text parsers. Yields (en, ja, score, meta).
    """
    path = str(path)
    if path.endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zf:
            yield from parse_members(zf.namelist(), zf.open)
    elif path.endswith(".tar.gz") or path.endswith(".tgz") or path.endswith(".tar"):
        with tarfile.open(path, "r:*") as tf:
            yield from parse_members(tf.getnames(), tf.extractfile)
    elif path.endswith(".txt") or path.endswith(".tsv"):
        yield from parse_text_file_lines(path)
    else:
        raise ValueError(f"Unsupported file type: {path}")


# -------------------------
# Extract metadata (LICENSE / CITATION / README)
# -------------------------
def extract_metadata_from_archive(path: str) -> Dict:
    """
    Search archive for README / LICENSE / CITATION files and return a dict of name->content.
    If path is a plain text file, returns empty dict.
    """
    metadata = {}
    path = str(path)
    if path.endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                lower = name.lower()
                if any(k in lower for k in ("license", "readme", "citation", "copying")):
                    try:
                        with zf.open(name) as fh:
                            content = fh.read().decode("utf-8", "replace")
                    except Exception:
                        content = ""
                    metadata[Path(name).name] = content
    elif path.endswith(".tar.gz") or path.endswith(".tgz") or path.endswith(".tar"):
        with tarfile.open(path, "r:*") as tf:
            for member in tf.getmembers():
                name = member.name
                lower = name.lower()
                if any(k in lower for k in ("license", "readme", "citation", "copying")):
                    try:
                        fh = tf.extractfile(member)
                        content = fh.read().decode("utf-8", "replace") if fh is not None else ""
                    except Exception:
                        content = ""
                    metadata[Path(name).name] = content
    return metadata


# -------------------------
# Batch processing
# -------------------------
def process_batch(cur, batch_pairs: List[Tuple[str, str, Optional[float], Dict]], en_lang_uid: int, ja_lang_uid: int, source_uid: int, domain_uid: int, direction_uid: int, method_uid: int):
    """
    Insert sentences and translations for a batch of pairs.
    batch_pairs: list of (en, ja, score, meta)
    """
    en_texts = [p[0] for p in batch_pairs]
    ja_texts = [p[1] for p in batch_pairs]

    en_map = batch_insert_sentences(cur, en_texts, en_lang_uid, source_uid, domain_uid)
    ja_map = batch_insert_sentences(cur, ja_texts, ja_lang_uid, source_uid, domain_uid)

    inserted_count = 0
    for en, ja, score, meta in batch_pairs:
        src_id = en_map.get(en)
        tgt_id = ja_map.get(ja)
        if not src_id or not tgt_id:
            continue
        insert_translation_if_not_exists(cur, src_id, tgt_id, direction_uid, method_uid)
        inserted_count += 1
        if score is not None:
            logging.debug("Alignment score for pair (src=%s tgt=%s): %s", src_id, tgt_id, score)
    logging.info("Batch: linked %d translations", inserted_count)


# -------------------------
# Main ingestion
# -------------------------
def ingest(file_path: str, batch_size: int = BATCH_SIZE):
    p = Path(file_path)
    if not p.exists():
        logging.info("File not found, auto-downloading %s -> %s", JPARA_URL, file_path)
        r = requests.get(JPARA_URL, stream=True)
        r.raise_for_status()
        with open(file_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=8192):
                fh.write(chunk)
        logging.info("Downloaded %s", file_path)

    logging.info("Extracting metadata (if archive)...")
    metadata = extract_metadata_from_archive(file_path)

    conn = get_conn()
    cur = conn.cursor()

    # ensure reference rows exist
    en_lang_uid = get_language_uid(cur, "en")
    ja_lang_uid = get_language_uid(cur, "ja")
    domain_uid = get_or_create_domain(cur, DEFAULT_DOMAIN_CODE, DEFAULT_DOMAIN_DESC)
    source_uid = get_or_create_source(cur, DEFAULT_SOURCE_TYPE, DEFAULT_SOURCE_NAME, author="OPUS", url="https://opus.nlpl.eu/", metadata=metadata)
    method_uid = get_or_create_method(cur, DEFAULT_METHOD_NAME, description="Parallel corpus ingestion", provider="OPUS")
    direction_uid = get_or_create_direction(cur, DEFAULT_DIRECTION_CODE, en_lang_uid, ja_lang_uid)

    conn.commit()

    batch: List[Tuple[str, str, Optional[float], Dict]] = []
    total = 0
    for en, ja, score, meta in parse_archive_or_file(file_path):
        batch.append((en, ja, score, meta))
        if len(batch) >= batch_size:
            process_batch(cur, batch, en_lang_uid, ja_lang_uid, source_uid, domain_uid, direction_uid, method_uid)
            conn.commit()
            total += len(batch)
            logging.info("Processed %s pairs (total %s)", len(batch), total)
            batch = []

    if batch:
        process_batch(cur, batch, en_lang_uid, ja_lang_uid, source_uid, domain_uid, direction_uid, method_uid)
        conn.commit()
        total += len(batch)

    cur.close()
    conn.close()
    logging.info("Ingestion finished. Total pairs processed: %s", total)


# -------------------------
# CLI
# -------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest JParaCrawl EN–JA into BhashaSetu.")
    parser.add_argument("--file", "-f", default=DEFAULT_LOCAL, help="Archive or text file (.zip, .tar.gz/.tgz/.tar, .txt, .tsv)")
    parser.add_argument("--batch", "-b", type=int, default=BATCH_SIZE, help="Batch size for DB inserts")
    args = parser.parse_args()
    ingest(args.file, batch_size=args.batch)
