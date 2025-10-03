# ingestion/webcrawl/review_app.py
from flask import Flask, request, jsonify, redirect
import sqlite3
import argparse
import json
import logging
from pathlib import Path

from .views import render_links_page, render_link_sentences_page

app = Flask(__name__)
DB_FILE = None
PAGE_SIZE = 20  # default, override from config


def get_conn():
    return sqlite3.connect(DB_FILE)


@app.route("/")
def index():
    page = int(request.args.get("page", 1))
    offset = (page - 1) * PAGE_SIZE

    conn = get_conn()
    cur = conn.cursor()

    # Total links
    cur.execute("SELECT COUNT(*) FROM links")
    total_links = cur.fetchone()[0] or 0

    # Sentence counts by status
    cur.execute("SELECT COUNT(*) FROM staging_sentences")
    total_sentences = cur.fetchone()[0] or 0

    cur.execute("""
        SELECT COALESCE(status, 'new') as status, COUNT(*) 
        FROM staging_sentences 
        GROUP BY COALESCE(status, 'new')
    """)
    status_rows = cur.fetchall()
    status_counts = {row[0]: row[1] for row in status_rows}

    # Paginated links
    cur.execute(f"""
        SELECT l.id, l.url,
            COUNT(s.id) as total,
            SUM(CASE WHEN COALESCE(s.status,'new')='new' THEN 1 ELSE 0 END) as new_count,
            SUM(CASE WHEN s.status='reviewed' THEN 1 ELSE 0 END) as reviewed_count,
            SUM(CASE WHEN s.status='rejected' THEN 1 ELSE 0 END) as rejected_count
        FROM links l
        LEFT JOIN staging_sentences s ON s.link_id = l.id
        GROUP BY l.id
        ORDER BY new_count DESC, l.id DESC
        LIMIT ? OFFSET ?
    """, (PAGE_SIZE, offset))
    rows = cur.fetchall()
    conn.close()

    links = [{
        "id": r[0],
        "url": r[1],
        "total": r[2],
        "new": r[3] or 0,
        "reviewed": r[4] or 0,
        "rejected": r[5] or 0
    } for r in rows]
    return render_links_page(
        links, page, PAGE_SIZE, total_links,
        total_sentences, status_counts
    )



@app.route("/link/<int:link_id>")
def view_link(link_id):
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", PAGE_SIZE))  # <-- dynamic page size
    status_filter = request.args.get("status", "new")  # can be None, 'new', 'reviewed', 'rejected'
    offset = (page - 1) * page_size

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT url FROM links WHERE id=? LIMIT 1", (link_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Link not found", 404
    link_url = row[0]

    # Build SQL condition
    where_clause = "WHERE link_id=?"
    params = [link_id]
    if status_filter in ("new", "reviewed", "rejected"):
        where_clause += " AND status=?"
        params.append(status_filter)

    # Count total
    cur.execute(f"SELECT COUNT(*) FROM staging_sentences {where_clause}", params)
    total = cur.fetchone()[0] or 0

    # Fetch sentences ASC order
    cur.execute(f"""
        SELECT id, sentence, status FROM staging_sentences
        {where_clause}
        ORDER BY id ASC
        LIMIT ? OFFSET ?
    """, params + [page_size, offset])
    rows = cur.fetchall()
    sentences = [{"id": r[0], "sentence": r[1], "status": r[2] or "new"} for r in rows]
    conn.close()

    return render_link_sentences_page(link_id, link_url, sentences, page, page_size, total, status_filter)



@app.route("/api/update_sentence", methods=["POST"])
def api_update_sentence():
    """
    - If payload contains "#$#" the text will be split into multiple sentences.
    - Splitting or editing allowed only for 'new' or 'rejected' sentences.
    - If split: delete original row, insert parts (status='new' for inserted parts).
    - If normal edit: update the row (only allowed for new/rejected).
    """
    payload = request.get_json(force=True)
    sid = payload.get("id")
    new_text = payload.get("sentence", "").strip()
    if not sid or new_text == "":
        return jsonify({"ok": False, "error": "invalid payload"}), 400

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT link_id, status FROM staging_sentences WHERE id=?", (sid,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "not found"}), 404
    link_id, status = row[0], (row[1] or "new")

    # Only allow edits/splits for 'new' or 'rejected'
    if status not in ("new", "rejected"):
        conn.close()
        return jsonify({"ok": False, "error": "cannot edit reviewed sentence"}, 403)

    # If split token exists, split into multiple parts
    if "#$#" in new_text:
        parts = [s.strip() for s in new_text.split("#$#") if s.strip()]
        if not parts:
            conn.close()
            return jsonify({"ok": False, "error": "invalid split parts"}), 400

        # Delete original
        cur.execute("DELETE FROM staging_sentences WHERE id=?", (sid,))
        # Insert parts with status='new'
        for part in parts:
            cur.execute(
                "INSERT INTO staging_sentences(link_id, sentence, status) VALUES (?, ?, ?)",
                (link_id, part, "new"),
            )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "split": True, "parts": parts})

    # Normal update (no split)
    cur.execute("UPDATE staging_sentences SET sentence=? WHERE id=?", (new_text, sid))
    conn.commit()
    updated = cur.rowcount
    conn.close()
    if updated:
        return jsonify({"ok": True, "split": False})
    else:
        return jsonify({"ok": False, "error": "not found"}), 404


@app.route("/api/delete_sentences", methods=["POST"])
def api_delete_sentences():
    payload = request.get_json(force=True)
    ids = payload.get("ids", [])
    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "error": "invalid ids"}), 400

    # Only allow deletion of new or rejected sentences; reviewed cannot be deleted
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, status FROM staging_sentences WHERE id IN ({seq})".format(seq=','.join(['?']*len(ids))), ids)
    rows = cur.fetchall()
    allowed = [r[0] for r in rows if (r[1] or "new") in ("new", "rejected")]
    if not allowed:
        conn.close()
        return jsonify({"ok": False, "error": "no deletable ids"}), 403

    cur.execute("DELETE FROM staging_sentences WHERE id IN ({seq})".format(seq=','.join(['?']*len(allowed))), allowed)
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/change_status", methods=["POST"])
def api_change_status():
    """
    Payload: { "ids": [1,2,3], "status": "reviewed"|"rejected"|"new" }
    Only 'reviewed' or 'rejected' are typical moves; allow 'new' to roll back.
    """
    payload = request.get_json(force=True)
    ids = payload.get("ids", [])
    status = payload.get("status", "").strip()
    if not isinstance(ids, list) or status not in ("new", "reviewed", "rejected"):
        return jsonify({"ok": False, "error": "invalid payload"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE staging_sentences SET status=? WHERE id IN ({seq})".format(seq=','.join(['?']*len(ids))), [status] + ids)
    updated = cur.rowcount
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "updated": updated})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sentence Review Web UI")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    args = parser.parse_args()

    # Load config
    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    DB_FILE = config["db_file"]
    review_conf = config.get("review", {})
    PAGE_SIZE = review_conf.get("page_size", 20)

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
