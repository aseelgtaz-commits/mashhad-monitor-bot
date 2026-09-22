import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Aden"))

class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or os.environ.get("DATABASE_PATH", "mashhad_monitor.db")
        self.init_db()
        self.seed_sources_from_json()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                enabled INTEGER DEFAULT 1
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER,
                title TEXT NOT NULL,
                link TEXT UNIQUE NOT NULL,
                content TEXT,
                mahra_score INTEGER DEFAULT 0,
                published_at TEXT,
                published_verified INTEGER DEFAULT 0,
                discovered_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sources (id)
            )""")
            cols = {r["name"] for r in cur.execute("PRAGMA table_info(items)").fetchall()}
            if "published_verified" not in cols:
                cur.execute("ALTER TABLE items ADD COLUMN published_verified INTEGER DEFAULT 0")
            if "discovered_at" not in cols:
                cur.execute("ALTER TABLE items ADD COLUMN discovered_at TEXT")
                cur.execute("UPDATE items SET discovered_at=? WHERE discovered_at IS NULL",
                            (datetime.now(timezone.utc).isoformat(),))
            cur.execute("UPDATE items SET published_verified=0 WHERE published_verified IS NULL")
            conn.commit()

    def seed_sources_from_json(self):
        if not os.path.exists("sources.json"):
            return
        try:
            with open("sources.json", "r", encoding="utf-8") as f:
                sources = json.load(f)
            with self.get_connection() as conn:
                for src in sources:
                    conn.execute("INSERT OR IGNORE INTO sources (name,url) VALUES (?,?)",
                                 (src["name"], src["url"]))
                conn.commit()
        except Exception as exc:
            logger.error("خطأ أثناء قراءة sources.json: %s", exc)

    def add_source(self, name, url):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO sources (name,url) VALUES (?,?)", (name,url))
            conn.commit()
            return cur.lastrowid

    def list_sources(self):
        with self.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id,name,url,enabled FROM sources ORDER BY id ASC").fetchall()]

    def remove_source(self, source_id):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
            conn.commit()

    def _today_window_utc(self):
        now = datetime.now(TIMEZONE)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.astimezone(timezone.utc).isoformat(), now.astimezone(timezone.utc).isoformat()

    def get_today_items(self):
        start, end = self._today_window_utc()
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT i.id,i.title,i.link,i.content,i.mahra_score,i.published_at,
                       i.discovered_at,i.published_verified,s.name AS source_name
                FROM items i JOIN sources s ON i.source_id=s.id
                WHERE i.published_verified=1
                  AND i.published_at>=? AND i.published_at<?
                ORDER BY i.published_at DESC,i.id DESC
            """, (start,end)).fetchall()
            return [dict(r) for r in rows]

    def save_item(self, source_id, title, link, content="", mahra_score=0,
                  published_at=None, published_verified=False):
        with self.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO items
                    (source_id,title,link,content,mahra_score,published_at,published_verified,discovered_at)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (source_id,title,link,content or "",int(mahra_score or 0),
                      published_at.isoformat() if published_at else None,
                      1 if published_verified and published_at else 0,
                      datetime.now(timezone.utc).isoformat()))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def dashboard_stats(self):
        with self.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            enabled = conn.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0]
            unverified = conn.execute("SELECT COUNT(*) FROM items WHERE published_verified=0").fetchone()[0]
        return {"sources": total, "enabled_sources": enabled,
                "items_today": len(self.get_today_items()),
                "published_today": len(self.get_today_items()),
                "unverified_items": unverified}

