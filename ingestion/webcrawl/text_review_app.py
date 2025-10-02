from flask import Flask, render_template_string, request
import sqlite3
import argparse
import json
import logging

app = Flask(__name__)
DB_FILE = None

TEMPLATE = """
<!doctype html>
<title>Sentence Review</title>
<h1>Review Gujarati Sentences</h1>
<form method="post">
  <table border="1" cellpadding="5">
    <tr><th>Select</th><th>Sentence</th><th>Source URL</th></tr>
    {% for row in rows %}
    <tr>
      <td><input type="checkbox" name="delete" value="{{ row[0] }}"></td>
      <td>{{ row[1] }}</td>
      <td><a href="{{ row[2] }}" target="_blank">{{ row[2] }}</a></td>
    </tr>
    {% endfor %}
  </table>
  <br>
  <input type="submit" value="Delete Selected">
</form>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if request.method == "POST":
        ids = request.form.getlist("delete")
        for i in ids:
            cur.execute("DELETE FROM staging_sentences WHERE id=?", (i,))
            logging.info(f"Deleted sentence id={i}")
        conn.commit()
    cur.execute("""SELECT staging_sentences.id, staging_sentences.sentence, links.url
                   FROM staging_sentences
                   JOIN links ON staging_sentences.link_id = links.id
                   ORDER BY staging_sentences.id DESC
                   LIMIT 100""")
    rows = cur.fetchall()
    conn.close()
    return render_template_string(TEMPLATE, rows=rows)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sentence Review Web UI")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    args = parser.parse_args()

    # Load config
    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    DB_FILE = config["db_file"]
    review_conf = config.get("review", {})

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
    logging.info(f"Starting review app on port {port}, DB={DB_FILE}")
    app.run(port=port, debug=True)
