import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "mashhad_monitor.db", timezone_name: str = "Asia/Aden"):
        self.db_path = db_path
        self.timezone_name = timezone_name
        self.tz = ZoneInfo(timezone_name)
        parent = Path(db_path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        self.init_db()
        self.seed_sources_from_json()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT UNIQUE NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    last_checked_at TEXT,
                    last_success_at TEXT,
                    last_error TEXT,
                    consecutive_errors INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER,
                    title TEXT NOT NULL,
                    link TEXT UNIQUE NOT NULL,
                    content TEXT,
                    mahra_score INTEGER DEFAULT 0,
                    matched_keywords TEXT,
                    published_at TEXT,
                    discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES sources (id)
                );

                CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at);
                CREATE INDEX IF NOT EXISTS idx_items_discovered_at ON items(discovered_at);
                CREATE INDEX IF NOT EXISTS idx_items_source_id ON items(source_id);
                """
            )
            self._ensure_column(conn, "sources", "last_checked_at", "TEXT")
            self._ensure_column(conn, "sources", "last_success_at", "TEXT")
            self._ensure_column(conn, "sources", "last_error", "TEXT")
            self._ensure_column(conn, "sources", "consecutive_errors", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "sources", "created_at", "TEXT")
            self._ensure_column(conn, "items", "matched_keywords", "TEXT")
            self._ensure_column(conn, "items", "discovered_at", "TEXT")
            conn.commit()

    @staticmethod
    def _ensure_column(conn, table: str, column: str, definition: str):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _now_utc(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def seed_sources_from_json(self):
        path = Path("sources.json")
        if not path.exists():
            logger.warning("sources.json غير موجود؛ سيتم استخدام المصادر الموجودة في قاعدة البيانات فقط.")
            return
        try:
            sources = json.loads(path.read_text(encoding="utf-8"))
            with self.get_connection() as conn:
                for source in sources:
                    name = str(source.get("name", "")).strip()
                    url = str(source.get("url", "")).strip()
                    if name and url:
                        conn.execute("INSERT OR IGNORE INTO sources (name, url) VALUES (?, ?)", (name, url))
                conn.commit()
            logger.info("تمت مزامنة المصادر من sources.json")
        except Exception:
            logger.exception("تعذر قراءة sources.json")

    def add_source(self, name: str, url: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("INSERT INTO sources (name, url) VALUES (?, ?)", (name.strip(), url.strip()))
            conn.commit()
            return int(cursor.lastrowid)

    def list_sources(self):
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, name, url, enabled, last_checked_at, last_success_at,
                       last_error, consecutive_errors, created_at
                FROM sources ORDER BY id ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def remove_source(self, source_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            conn.commit()

    def mark_source_result(self, source_id: int, success: bool, error: str | None = None):
        now = self._now_utc()
        with self.get_connection() as conn:
            if success:
                conn.execute(
                    """UPDATE sources
                       SET last_checked_at=?, last_success_at=?, last_error=NULL, consecutive_errors=0
                       WHERE id=?""",
                    (now, now, source_id),
                )
            else:
                conn.execute(
                    """UPDATE sources
                       SET last_checked_at=?, last_error=?, consecutive_errors=COALESCE(consecutive_errors,0)+1
                       WHERE id=?""",
                    (now, (error or "خطأ غير معروف")[:2000], source_id),
                )
            conn.commit()

    def save_item(
        self,
        source_id: int,
        title: str,
        link: str,
        content: str = "",
        mahra_score: int = 0,
        matched_keywords: list[str] | None = None,
        published_at: str | None = None,
    ) -> bool:
        if not title or not link:
            return False
        discovered_at = self._now_utc()
        keywords_json = json.dumps(matched_keywords or [], ensure_ascii=False)
        try:
            with self.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO items
                    (source_id, title, link, content, mahra_score, matched_keywords, published_at, discovered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (source_id, title.strip(), link.strip(), content or "", int(mahra_score), keywords_json,
                     published_at or discovered_at, discovered_at),
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def _today_bounds_utc(self):
        local_now = datetime.now(self.tz)
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        next_local = start_local.replace(day=start_local.day + 1) if start_local.day < 28 else None
        if next_local is None:
            from datetime import timedelta
            next_local = start_local + timedelta(days=1)
        return start_local.astimezone(timezone.utc), next_local.astimezone(timezone.utc)

    def get_today_items(self):
        start_utc, end_utc = self._today_bounds_utc()
        start_s = start_utc.isoformat(timespec="seconds")
        end_s = end_utc.isoformat(timespec="seconds")
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT i.id, i.title, i.link, i.content, i.mahra_score, i.matched_keywords,
                       i.published_at, i.discovered_at, s.name AS source_name, s.url AS source_url
                FROM items i
                JOIN sources s ON i.source_id = s.id
                WHERE COALESCE(i.published_at, i.discovered_at) >= ?
                  AND COALESCE(i.published_at, i.discovered_at) < ?
                ORDER BY COALESCE(i.published_at, i.discovered_at) DESC, i.id DESC
                """,
                (start_s, end_s),
            ).fetchall()
            return [dict(row) for row in rows]

    def dashboard_stats(self):
        with self.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            enabled = conn.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0]
            errors = conn.execute("SELECT COUNT(*) FROM sources WHERE enabled=1 AND consecutive_errors > 0").fetchone()[0]
        today = self.get_today_items()
        return {
            "sources": total,
            "enabled_sources": enabled,
            "items_today": len(today),
            "source_errors": errors,
        }

