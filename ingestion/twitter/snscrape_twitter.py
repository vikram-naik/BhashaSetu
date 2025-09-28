#!/usr/bin/env python3
"""
Twitter (X) Ingestion Script for BhashaSetu
-------------------------------------------
- Uses snscrape to fetch Japanese tweets
- Cleans text (removes URLs, mentions, RTs, emojis optional)
- Inserts into PostgreSQL (sentence + source tables)
"""

import os
import re
import json
import subprocess
import psycopg2
from psycopg2.extras import Json

# -----------------------------
# Config
# -----------------------------
DB_NAME = os.getenv("BHASHA_DB", "bhashasetu")
DB_USER = os.getenv("BHASHA_USER", "bhasha_user")
DB_PASS = os.getenv("BHASHA_PASS", "")
DB_HOST = os.getenv("BHASHA_HOST", "localhost")

LANG_JA_UID = 1   # you will seed this in bhashasetu-seed.sql
DOMAIN_SOCIAL_UID = 1  # "social-media"
SOURCE_TWITTER_UID = 1 # Twitter base source

# -----------------------------
# Helpers
# -----------------------------

def clean_tweet(text: str) -> str:
    """Basic cleanup for Japanese tweets."""
    text = re.sub(r"http\S+", "", text)          # remove URLs
    text = re.sub(r"@\w+", "", text)             # remove mentions
    text = re.sub(r"RT\s+", "", text)            # remove RT
    text = text.strip()
    return text

def fetch_tweets(query: str, limit: int = 100):
    """Fetch tweets via snscrape (returns list of dicts)."""
    cmd = [
        "snscrape",
        "--jsonl",
        "-n", str(limit),
        "twitter-search",
        query,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print("❌ snscrape failed!")
        print("stderr:", e.stderr)
        print("stdout:", e.stdout)
        return []

    tweets = []
    for line in result.stdout.splitlines():
        try:
            tweets.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return tweets



def insert_into_db(tweets):
    """Insert tweets into PostgreSQL sentence + source."""
    conn = psycopg2.connect(
        dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST
    )
    cur = conn.cursor()

    for t in tweets:
        text = clean_tweet(t["content"])
        if not text or len(text) < 3:
            continue

        # Insert sentence
        cur.execute(
            """
            INSERT INTO bhashasetu.sentence (text, language_uid, source_uid, domain_uid)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (text, LANG_JA_UID, SOURCE_TWITTER_UID, DOMAIN_SOCIAL_UID),
        )
        sent_id = cur.fetchone()[0]

        # Update source metadata
        metadata = {
            "tweet_id": t.get("id"),
            "date": t.get("date"),
            "username": t.get("user", {}).get("username"),
            "likeCount": t.get("likeCount"),
            "retweetCount": t.get("retweetCount"),
        }

        cur.execute(
            """
            UPDATE bhashasetu.source
            SET metadata = metadata || %s::jsonb
            WHERE source_uid = %s
            """,
            (Json(metadata), SOURCE_TWITTER_UID),
        )

    conn.commit()
    cur.close()
    conn.close()

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    # Example: fetch Japanese tweets about 映画 (movies)
    tweets = fetch_tweets("映画 lang:ja since:2025-01-01 until:2025-01-10", limit=50)
    insert_into_db(tweets)
    print(f"Inserted {len(tweets)} tweets into BhashaSetu.")
