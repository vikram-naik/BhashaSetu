#!/usr/bin/env python3
"""
backfill_and_mark_duplicates.py
---------------------------------------
Compute hashes for existing sentences, detect duplicates,
and mark duplicates with status='duplicate' and duplicate_of pointing to the first occurrence.
"""

import sqlite3
import hashlib
import unicodedata
import re
import sys
from tqdm import tqdm

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\s+", " ", text.strip().lower())
    return text

def compute_hash(text: str) -> str:
    norm = normalize_text(text)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()

def ensure_schema(conn):
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(staging_sentences)").fetchall()]
    if "hash" not in cols:
        cur.execute("ALTER TABLE staging_sentences ADD COLUMN hash TEXT")
    if "duplicate_of" not in cols:
        cur.execute("ALTER TABLE staging_sentences ADD COLUMN duplicate_of INTEGER")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_staging_sent_hash ON staging_sentences(hash)")
    conn.commit()

def main(db_path: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    ensure_schema(conn)

    # 1️⃣ Backfill hashes for missing
    cur.execute("SELECT id, sentence FROM staging_sentences WHERE hash IS NULL OR hash=''")
    rows = cur.fetchall()
    if rows:
        print(f"⚙️  Populating hashes for {len(rows)} missing rows...")
        for sid, sentence in tqdm(rows, disable=not sys.stdout.isatty()):
            if not sentence:
                continue
            h = compute_hash(sentence)
            cur.execute("UPDATE staging_sentences SET hash=? WHERE id=?", (h, sid))
        conn.commit()
    else:
        print("✅ All rows already have hashes.")

    # 2️⃣ Find duplicate hashes
    print("🔍 Checking for duplicates...")
    cur.execute("""
        SELECT hash, COUNT(*) as cnt
        FROM staging_sentences
        WHERE hash IS NOT NULL AND hash != ''
        GROUP BY hash
        HAVING cnt > 1
    """)
    dup_hashes = cur.fetchall()

    if not dup_hashes:
        print("✅ No duplicates found.")
        conn.close()
        return

    total_dups = 0
    for h, cnt in tqdm(dup_hashes, disable=not sys.stdout.isatty()):
        # Select all rows sharing this hash, ordered by smallest id = original
        cur.execute("""
            SELECT id FROM staging_sentences
            WHERE hash=?
            ORDER BY id ASC
        """, (h,))
        ids = [r[0] for r in cur.fetchall()]
        if len(ids) < 2:
            continue

        original_id = ids[0]
        dup_ids = ids[1:]
        total_dups += len(dup_ids)

        # Mark duplicates
        cur.executemany("""
            UPDATE staging_sentences
            SET status='duplicate', duplicate_of=?
            WHERE id=?
        """, [(original_id, dup_id) for dup_id in dup_ids])

    conn.commit()
    conn.close()
    print(f"✅ Done. Marked {total_dups} existing sentences as duplicates.")
    print("💾 All duplicates now have status='duplicate' and duplicate_of set to the first occurrence.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backfill_and_mark_duplicates.py <path_to_sqlite_db>")
        sys.exit(1)
    main(sys.argv[1])
