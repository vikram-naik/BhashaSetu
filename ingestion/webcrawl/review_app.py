# ingestion/webcrawl/review_app.py
from flask import Flask, abort, render_template, request, jsonify, redirect
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


# ==========================================================
# --- ROUTES ---
# ==========================================================

@app.route("/")
def index():
    page = int(request.args.get("page", 1))
    offset = (page - 1) * PAGE_SIZE

    conn = get_conn()
    cur = conn.cursor()

    # Total links
    cur.execute("""
        SELECT COUNT(DISTINCT l.id)
        FROM links l
        JOIN staging_sentences s ON s.link_id = l.id
        WHERE s.status = 'new'
    """)
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

    # Ensure all expected keys are present
    for key in ("new", "reviewed", "rejected", "duplicate"):
        status_counts.setdefault(key, 0)

    cur.execute("""
        SELECT COALESCE(d.name, 'Untagged') AS domain, COUNT(s.id), d.id
        FROM staging_sentences s
        LEFT JOIN staging_sentence_domain sd ON sd.sentence_id = s.id
        LEFT JOIN domain d ON d.id = sd.domain_id
        WHERE s.status = 'reviewed'
        GROUP BY COALESCE(d.name, 'Untagged')
        ORDER BY COUNT(s.id) DESC
    """)
    domain_rows = cur.fetchall()
    domain_counts = {row[0]: (row[1], row[2]) for row in domain_rows}

    if not domain_rows:
        domain_counts = {"(no reviewed sentences yet)": (0,0)}

    # Paginated links
    cur.execute(f"""
        SELECT l.id, l.url,
            COUNT(s.id) AS total,
            SUM(CASE WHEN s.status='new' THEN 1 ELSE 0 END) AS new,
            SUM(CASE WHEN s.status='reviewed' THEN 1 ELSE 0 END) AS reviewed,
            SUM(CASE WHEN s.status='rejected' THEN 1 ELSE 0 END) AS rejected,
            SUM(CASE WHEN s.status='duplicate' THEN 1 ELSE 0 END) AS duplicate
        FROM links l
        LEFT JOIN staging_sentences s ON s.link_id = l.id
        GROUP BY l.id, l.url
        HAVING new > 0
        ORDER BY new DESC, total DESC, l.id DESC
        LIMIT ? OFFSET ?
    """, (PAGE_SIZE, offset))
    rows = cur.fetchall()
    conn.close()

    links = [
        {
            "id": row[0],
            "url": row[1],
            "total": row[2],
            "new": row[3],
            "reviewed": row[4],
            "rejected": row[5],
            "duplicate": row[6],
        }
        for row in rows
    ]
    return render_links_page(
        links, page, PAGE_SIZE, total_links,
        total_sentences, status_counts,
        domain_counts=domain_counts
    )


@app.route("/link/<int:link_id>")
def view_link(link_id):
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", PAGE_SIZE))
    status_filter = request.args.get("status", "new")
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
    if status_filter in ("new", "reviewed", "rejected", "duplicate"):
        where_clause += " AND status=?"
        params.append(status_filter)

    # Count total
    cur.execute(f"SELECT COUNT(*) FROM staging_sentences {where_clause}", params)
    total = cur.fetchone()[0] or 0

    # Fetch sentences
    cur.execute(f"""
        SELECT s.id, s.sentence, s.status,
            COALESCE(d.id, 0) as domain_id,
            COALESCE(d.name, 'Untagged') as domain_name
        FROM staging_sentences s
        LEFT JOIN staging_sentence_domain sd ON sd.sentence_id = s.id
        LEFT JOIN domain d ON d.id = sd.domain_id
        {where_clause}
        ORDER BY s.created_at ASC, s.id ASC
        LIMIT ? OFFSET ?
    """, params + [page_size, offset])

    rows = cur.fetchall()

    sentences = [{
        "id": r[0],
        "sentence": r[1],
        "status": r[2] or "new",
        "domain_id": r[3],
        "domain_name": r[4] or "Untagged"
    } for r in rows]

    # Domain dropdown
    cur.execute("SELECT id, name FROM domain ORDER BY name")
    domain_options = [{"id": r[0], "name": r[1]} for r in cur.fetchall()]
    conn.close()

    return render_link_sentences_page(
        link_id, link_url, sentences, page, page_size,
        total, status_filter, domain_options
    )

# ==========================================================
# --- API ROUTES ---
# ==========================================================

@app.route("/api/update_sentence", methods=["POST"])
def api_update_sentence():
    payload = request.get_json(force=True)
    sid = payload.get("id")
    new_text = payload.get("sentence", "").strip()
    if not sid or not new_text:
        return jsonify({"ok": False, "error": "invalid payload"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT link_id, status FROM staging_sentences WHERE id=?", (sid,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "not found"}), 404

    link_id, status = row
    status = status or "new"

    if status not in ("new", "rejected"):
        conn.close()
        return jsonify({"ok": False, "error": "cannot edit reviewed sentence"}), 403

    if "#$#" in new_text:
        parts = [p.strip() for p in new_text.split("#$#") if p.strip()]
        if not parts:
            conn.close()
            return jsonify({"ok": False, "error": "invalid split parts"}), 400
        cur.execute("DELETE FROM staging_sentences WHERE id=?", (sid,))
        for p in parts:
            cur.execute(
                "INSERT INTO staging_sentences(link_id, sentence, status) VALUES (?, ?, 'new')",
                (link_id, p),
            )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "split": True, "parts": parts})

    cur.execute("UPDATE staging_sentences SET sentence=? WHERE id=?", (new_text, sid))
    conn.commit()
    updated = cur.rowcount
    conn.close()
    return jsonify({"ok": bool(updated)})


@app.route("/api/delete_sentences", methods=["POST"])
def api_delete_sentences():
    payload = request.get_json(force=True)
    ids = payload.get("ids", [])
    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "error": "invalid ids"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"SELECT id, status FROM staging_sentences WHERE id IN ({','.join(['?']*len(ids))})",
        ids
    )
    rows = cur.fetchall()
    allowed = [r[0] for r in rows if (r[1] or "new") in ("new", "rejected", "duplicate")]
    if not allowed:
        conn.close()
        return jsonify({"ok": False, "error": "no deletable ids"}), 403

    cur.execute(
        f"DELETE FROM staging_sentences WHERE id IN ({','.join(['?']*len(allowed))})",
        allowed
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/update_status_bulk", methods=["POST"])
def api_update_status_bulk():
    """
    Payload: { "ids": [1,2,3], "status": "reviewed"|"rejected"|"new" }
    Prevents marking as 'reviewed' if any sentence is untagged.
    """
    payload = request.get_json(force=True)
    ids = payload.get("ids", [])
    status = payload.get("status", "").strip()

    if not ids or not isinstance(ids, list) or status not in ("new", "reviewed", "rejected"):
        return jsonify({"ok": False, "error": "invalid payload"}), 400

    try:
        conn = get_conn()
        cur = conn.cursor()

        # 🚫 Prevent review if any sentence is untagged (no domain)
        if status == "reviewed":
            placeholders = ",".join("?" for _ in ids)
            cur.execute(f"""
                SELECT COUNT(*) FROM staging_sentences s
                LEFT JOIN staging_sentence_domain sd ON sd.sentence_id = s.id
                WHERE s.id IN ({placeholders}) AND sd.domain_id IS NULL
            """, ids)
            untagged_count = cur.fetchone()[0] or 0
            if untagged_count > 0:
                conn.close()
                return jsonify({
                    "ok": False,
                    "error": f"{untagged_count} sentence(s) are untagged. Assign a domain before marking as reviewed."
                }), 400

        # ✅ Perform status update
        placeholders = ",".join("?" for _ in ids)
        cur.execute(
            f"UPDATE staging_sentences SET status=? WHERE id IN ({placeholders})",
            [status] + ids,
        )
        updated = cur.rowcount
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "updated": updated})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/update_domain", methods=["POST"])
def api_update_domain():
    payload = request.get_json(force=True)
    sid = payload.get("sentence_id")
    did = payload.get("domain_id")

    if not sid:
        return jsonify({"ok": False, "error": "missing sentence_id"}), 400

    conn = get_conn()
    cur = conn.cursor()

    # Handle explicit untagged
    if not did or did == "untagged":
        cur.execute("DELETE FROM staging_sentence_domain WHERE sentence_id=?", (sid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "untagged": True, "domain_name": "Untagged"})

    # Convert to int safely
    try:
        did = int(did)
    except ValueError:
        conn.close()
        return jsonify({"ok": False, "error": "invalid domain id"}), 400

    # Validate IDs
    cur.execute("SELECT 1 FROM staging_sentences WHERE id=?", (sid,))
    if not cur.fetchone():
        conn.close()
        return jsonify({"ok": False, "error": "invalid sentence"}), 404

    cur.execute("SELECT name FROM domain WHERE id=?", (did,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "invalid domain"}), 404
    domain_name = row[0]

    # Update / insert mapping
    cur.execute("""
        INSERT OR REPLACE INTO staging_sentence_domain (sentence_id, domain_id, source)
        VALUES (?, ?, 'manual_review')
    """, (sid, did))

    conn.commit()
    conn.close()
    return jsonify({"ok": True, "domain_id": did, "domain_name": domain_name})


@app.route("/domain/<int:domain_id>")
def view_domain(domain_id):
    """
    Show sentences associated with a domain (via staging_sentence_domain mapping).
    Query params:
      - page (int) default 1
      - status (str) default 'reviewed' 
      - page_size (int) default from config or PAGE_SIZE
    Renders sentences.html (same view used for link-based review) and passes:
      sentences, domain_name, domain_id, page, page_size, total, total_pages, start, end, status
    """
    conn = get_conn()
    try:
        cur = conn.cursor()

        # params
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1
        status = request.args.get("status", "reviewed")
        try:
            page_size = int(request.args.get("page_size", PAGE_SIZE))
            if page_size <= 0:
                page_size = PAGE_SIZE
        except Exception:
            page_size = PAGE_SIZE

        offset = (page - 1) * page_size

        # validate domain exists
        cur.execute("SELECT id, name FROM domain WHERE id = ?", (domain_id,))
        drow = cur.fetchone()
        if not drow:
            conn.close()
            return abort(404, f"Domain id {domain_id} not found")
        domain_name = drow[1]

        # total count for pagination (apply status filter if requested)
        if status == "all":
            cur.execute("""
                SELECT COUNT(*)
                FROM staging_sentences s
                JOIN staging_sentence_domain sd ON sd.sentence_id = s.id
                WHERE sd.domain_id = ?
            """, (domain_id,))
        else:
            cur.execute("""
                SELECT COUNT(*)
                FROM staging_sentences s
                JOIN staging_sentence_domain sd ON sd.sentence_id = s.id
                WHERE sd.domain_id = ? AND s.status = ?
            """, (domain_id, status))
        total = cur.fetchone()[0] or 0
        total_pages = (total + page_size - 1) // page_size if page_size else 1

        # fetch sentences (with link info and domain info) ordered by insertion time then id
        if status == "all":
            q = """
                SELECT s.id, s.sentence, COALESCE(s.status, 'new') as status,
                       l.id AS link_id, l.url AS link_url,
                       d.id AS domain_id, d.name AS domain_name,
                       s.created_at
                FROM staging_sentences s
                JOIN staging_sentence_domain sd ON sd.sentence_id = s.id
                LEFT JOIN links l ON l.id = s.link_id
                LEFT JOIN domain d ON d.id = sd.domain_id
                WHERE sd.domain_id = ?
                ORDER BY s.created_at ASC, s.id ASC
                LIMIT ? OFFSET ?
            """
            params = (domain_id, page_size, offset)
        else:
            q = """
                SELECT s.id, s.sentence, COALESCE(s.status, 'new') as status,
                       l.id AS link_id, l.url AS link_url,
                       d.id AS domain_id, d.name AS domain_name,
                       s.created_at
                FROM staging_sentences s
                JOIN staging_sentence_domain sd ON sd.sentence_id = s.id
                LEFT JOIN links l ON l.id = s.link_id
                LEFT JOIN domain d ON d.id = sd.domain_id
                WHERE sd.domain_id = ? AND s.status = ?
                ORDER BY s.created_at ASC, s.id ASC
                LIMIT ? OFFSET ?
            """
            params = (domain_id, status, page_size, offset)

        cur.execute(q, params)
        rows = cur.fetchall()

        sentences = []
        for row in rows:
            sid, text, st, link_id, link_url, did, dname, created_at = row
            sentences.append({
                "id": sid,
                "sentence": text,
                "status": st,
                "link_id": link_id,
                "link_url": link_url,
                "domain_id": did,
                "domain_name": dname,
                "created_at": created_at
            })

        start = offset + 1 if total > 0 else 0
        end = min(offset + page_size, total)

        # Domain dropdown
        cur.execute("SELECT id, name FROM domain ORDER BY name")
        domain_options = [{"id": r[0], "name": r[1]} for r in cur.fetchall()]

        # Render the same review template, with a flag so the template can show domain-specific heading
        return render_template(
            "sentences.html",
            sentences=sentences,
            domain_name=domain_name,
            domain_id=domain_id,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            start=start,
            end=end,
            status=status,
            from_domain=True,
            domain_options=domain_options
        )
    finally:
        conn.close()


# ==========================================================
# --- ENTRYPOINT ---
# ==========================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sentence Review Web UI")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    DB_FILE = config["db_file"]
    review_conf = config.get("review", {})
    PAGE_SIZE = review_conf.get("page_size", 20)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(review_conf.get("log_file", "review.log"), encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    port = review_conf.get("port", 5000)
    logging.info(f"Starting review app on port {port}, DB={DB_FILE}, page_size={PAGE_SIZE}")
    app.run(port=port, debug=True)
