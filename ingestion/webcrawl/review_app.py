# ingestion/webcrawl/review_app.py
# Server layer: routes, DB interactions, API for update/delete

from flask import Flask, request, jsonify, redirect
import sqlite3
import argparse
import json
import logging
import math
from pathlib import Path

# relative import (same folder)
from .views import render_links_page, render_link_sentences_page

app = Flask(__name__)
DB_FILE = None
PAGE_SIZE = 20  # default, overridden by config

def get_conn():
    return sqlite3.connect(DB_FILE)

@app.route("/")
def index():
    # pagination for links
    page = int(request.args.get("page", 1))
    page_size = PAGE_SIZE
    offset = (page - 1) * page_size

    conn = get_conn()
    cur = conn.cursor()
    # get total link count with any sentences present
    cur.execute("SELECT COUNT(*) FROM links")
    total_links = cur.fetchone()[0] or 0

    # select links with sentence counts
    cur.execute("""
        SELECT l.id, l.url, COUNT(s.id) as cnt
        FROM links l
        LEFT JOIN staging_sentences s ON s.link_id = l.id
        GROUP BY l.id
        ORDER BY cnt DESC, l.id DESC
        LIMIT ? OFFSET ?
    """, (page_size, offset))
    rows = cur.fetchall()
    conn.close()

    links = [{"id": r[0], "url": r[1], "count": r[2]} for r in rows]
    return render_links_page(links, page, page_size, total_links)

@app.route("/link/<int:link_id>")
def view_link(link_id):
    page = int(request.args.get("page", 1))
    page_size = PAGE_SIZE
    offset = (page - 1) * page_size

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT url FROM links WHERE id=? LIMIT 1", (link_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Link not found", 404
    link_url = row[0]

    # total sentences for this link
    cur.execute("SELECT COUNT(*) FROM staging_sentences WHERE link_id=?", (link_id,))
    total = cur.fetchone()[0] or 0

    # fetch sentences paginated (latest first)
    cur.execute("""
        SELECT id, sentence FROM staging_sentences
        WHERE link_id=?
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """, (link_id, page_size, offset))
    rows = cur.fetchall()
    sentences = [{"id": r[0], "sentence": r[1]} for r in rows]
    conn.close()
    return render_link_sentences_page(link_id, link_url, sentences, page, page_size, total)

# API: update a sentence
@app.route("/api/update_sentence", methods=["POST"])
def api_update_sentence():
    payload = request.get_json(force=True)
    sid = payload.get("id")
    new_text = payload.get("sentence", "").strip()
    if not sid or new_text == "":
        return jsonify({"ok": False, "error": "invalid payload"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE staging_sentences SET sentence=? WHERE id=?", (new_text, sid))
    conn.commit()
    updated = cur.rowcount
    conn.close()
    if updated:
        return jsonify({"ok": True})
    else:
        return jsonify({"ok": False, "error": "not found"}), 404

# API: delete sentences (ids list)
@app.route("/api/delete_sentences", methods=["POST"])
def api_delete_sentences():
    payload = request.get_json(force=True)
    ids = payload.get("ids", [])
    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "error": "invalid ids"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM staging_sentences WHERE id IN ({seq})".format(
        seq=','.join(['?']*len(ids))
    ), ids)
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "deleted": deleted})

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sentence Review Web UI")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    args = parser.parse_args()

    # Load config
    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    DB_FILE = config["db_file"]
    review_conf = config.get("review", {})
    PAGE_SIZE = review_conf.get("page_size", review_conf.get("page_size", 20))

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(review_conf.get("log_file", "review.log"), encoding="utf-8"),
            logging.StreamHandler()
        ]
    )

    port = review_conf.get("port", 5000)
    logging.info(f"Starting review app on port {port}, DB={DB_FILE}, page_size={PAGE_SIZE}")
    app.run(port=port, debug=True)
