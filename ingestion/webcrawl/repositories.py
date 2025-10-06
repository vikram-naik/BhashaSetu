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
        return cur.lastrowid   # ✅ return new sentence id

def init_db(conn):
    cur = conn.cursor()

    # Existing tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staging_sentences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id INTEGER,
            sentence TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (link_id) REFERENCES links (id)
        )
    """)

    # New domain metadata tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS domain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            name TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staging_sentence_domain (
            sentence_id INTEGER UNIQUE,
            domain_id INTEGER,
            confidence REAL DEFAULT NULL,
            source TEXT DEFAULT 'rule_based',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sentence_id) REFERENCES staging_sentences (id),
            FOREIGN KEY (domain_id) REFERENCES domain (id)
        )
    """)

    conn.commit()


class DomainRepository:
    """Manages domain reference table."""
    def __init__(self, conn):
        self.conn = conn

    def get_or_create(self, code, name, description=None):
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM domain WHERE code=?", (code,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("INSERT INTO domain (code, name, description) VALUES (?, ?, ?)",
                    (code, name, description))
        self.conn.commit()
        return cur.lastrowid


class SentenceDomainRepository:
    """Manages mappings between sentences and domains."""
    def __init__(self, conn):
        self.conn = conn

    def insert(self, sentence_id, domain_id, confidence=None, source="rule_based"):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO staging_sentence_domain (sentence_id, domain_id, confidence, source)
            VALUES (?, ?, ?, ?)
        """, (sentence_id, domain_id, confidence, source))
        self.conn.commit()
