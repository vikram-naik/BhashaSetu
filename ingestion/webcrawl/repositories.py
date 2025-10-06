import sqlite3

class LinkRepository:
    def __init__(self, conn): 
        self.conn = conn

    def exists(self, url):
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM links WHERE url=? LIMIT 1", (url,))
        return cur.fetchone() is not None

    def insert(self, url):
        cur = self.conn.cursor()
        cur.execute("INSERT OR IGNORE INTO links(url) VALUES (?)", (url,))
        self.conn.commit()
        cur.execute("SELECT id FROM links WHERE url=? LIMIT 1", (url,))
        return cur.fetchone()[0]


class SentenceRepository:
    def __init__(self, conn): 
        self.conn = conn

    def insert(self, link_id, sentence, status="new"):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO staging_sentences(link_id, sentence, status) VALUES (?, ?, ?)",
            (link_id, sentence, status)
        )
        self.conn.commit()


def init_db(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staging_sentences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id INTEGER,
            sentence TEXT,
            status TEXT DEFAULT 'new',
            FOREIGN KEY(link_id) REFERENCES links(id)
        )
    """)
    conn.commit()
