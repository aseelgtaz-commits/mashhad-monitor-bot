import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str | None = None, timezone_name: str = "Asia/Aden"):
        self.db_path = db_path or os.getenv("DATABASE_PATH", "mashhad_monitor.db")
        self.timezone_name = timezone_name
        self.local_timezone = ZoneInfo(timezone_name)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True) if Path(self.db_path).parent != Path(".") else None
        self.init_db()
        self.seed_sources_from_json()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        with self.get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT UNIQUE NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_checked_at TEXT,
                    last_success_at TEXT,
                    last_error TEXT,
                    consecutive_errors INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER,
                    title TEXT NOT NULL,
                    link TEXT UNIQUE NOT NULL,
                    content TEXT,
                    mahra_score INTEGER NOT NULL DEFAULT 0,
                    matched_keywords TEXT,
                    published_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_items_discovered_at ON items(discovered_at);
                CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at);
                CREATE INDEX IF NOT EXISTS idx_items_source_id ON items(source_id);
                """
            )
            conn.commit()

    def seed_sources_from_json(self, path: str = "sources.json") -> None:
        source_path = Path(path)
        if not source_path.exists():
            return
        try:
            data = json.loads(source_path.read_text(encoding="utf-8"))
            with self.get_connection() as conn:
                for src in data:
                    name = str(src.get("name", "")).strip()
                    url = str(src.get("url", "")).strip()
                    if not name or not url:
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO sources (name, url, enabled) VALUES (?, ?, 1)",
                        (name, url),
                    )
                conn.commit()
            logger.info("تمت مزامنة المصادر من %s", source_path)
        except Exception:
            logger.exception("تعذر قراءة %s", source_path)

    def add_source(self, name: str, url: str) -> int:
        with self.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO sources (name, url, enabled) VALUES (?, ?, 1)",
                (name.strip(), url.strip()),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_sources(self, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM sources"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id ASC"
        with self.get_connection() as conn:
            return [dict(row) for row in conn.execute(sql).fetchall()]

    def remove_source(self, source_id: int) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            conn.commit()
            return cur.rowcount > 0

    def set_source_enabled(self, source_id: int, enabled: bool) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute(
                "UPDATE sources SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, source_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def mark_source_result(self, source_id: int, success: bool, error: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            if success:
                conn.execute(
                    """UPDATE sources
                       SET last_checked_at = ?, last_success_at = ?, last_error = NULL,
                           consecutive_errors = 0
                       WHERE id = ?""",
                    (now, now, source_id),
                )
            else:
                conn.execute(
                    """UPDATE sources
                       SET last_checked_at = ?, last_error = ?,
                           consecutive_errors = consecutive_errors + 1
                       WHERE id = ?""",
                    (now, (error or "Unknown error")[:1000], source_id),
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
        title = (title or "").strip()
        link = (link or "").strip()
        if not title or not link:
            return False

        published_at = published_at or datetime.now(timezone.utc).isoformat()
        keywords_json = json.dumps(matched_keywords or [], ensure_ascii=False)
        with self.get_connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO items
                       (source_id, title, link, content, mahra_score, matched_keywords, published_at, discovered_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        source_id,
                        title,
                        link,
                        content or "",
                        int(mahra_score),
                        keywords_json,
                        published_at,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def _today_bounds_utc(self) -> tuple[str, str]:
        now_local = datetime.now(self.local_timezone)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        return start_local.astimezone(timezone.utc).isoformat(), end_local.astimezone(timezone.utc).isoformat()

    def get_today_items(self, limit: int | None = None) -> list[dict]:
        start_utc, end_utc = self._today_bounds_utc()
        sql = """
            SELECT i.id, i.title, i.link, i.content, i.mahra_score,
                   i.matched_keywords, i.published_at, i.discovered_at,
                   s.name AS source_name
            FROM items i
            LEFT JOIN sources s ON i.source_id = s.id
            WHERE i.discovered_at >= ? AND i.discovered_at < ?
            ORDER BY i.id DESC
        """
        params: list = [start_utc, end_utc]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self.get_connection() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        for row in rows:
            try:
                row["matched_keywords"] = json.loads(row.get("matched_keywords") or "[]")
            except json.JSONDecodeError:
                row["matched_keywords"] = []
        return rows

    def dashboard_stats(self) -> dict:
        start_utc, end_utc = self._today_bounds_utc()
        with self.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            enabled = conn.execute("SELECT COUNT(*) FROM sources WHERE enabled = 1").fetchone()[0]
            today = conn.execute(
                "SELECT COUNT(*) FROM items WHERE discovered_at >= ? AND discovered_at < ?",
                (start_utc, end_utc),
            ).fetchone()[0]
            errors = conn.execute(
                "SELECT COUNT(*) FROM sources WHERE enabled = 1 AND consecutive_errors > 0"
            ).fetchone()[0]
            return {
                "sources": total,
                "enabled_sources": enabled,
                "items_today": today,
                "sources_with_errors": errors,
            }

    def build_daily_report(self, max_items: int = 50) -> str:
        items = self.get_today_items(limit=max_items)
        stats = self.dashboard_stats()
        lines = [
            "🛰 <b>التقرير اليومي لرصد المهرة</b>",
            f"📡 <b>المصادر النشطة:</b> {stats['enabled_sources']}",
            f"📰 <b>المواد المرصودة اليوم:</b> {stats['items_today']}",
            f"⚠️ <b>مصادر لديها أخطاء:</b> {stats['sources_with_errors']}",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        if not items:
            lines.append("لم يتم رصد مواد متعلقة بالمهرة خلال اليوم.")
        else:
            lines.append("🔴 <b>أبرز المواد المرصودة</b>")
            for idx, item in enumerate(items, 1):
                title = item["title"].replace("<", "&lt;").replace(">", "&gt;")
                source = (item.get("source_name") or "مصدر غير معروف").replace("<", "&lt;").replace(">", "&gt;")
                link = item["link"]
                lines.append(f"<b>{idx}. {title}</b>\n🔹 <b>المصدر:</b> {source}\n🔗 <a href=\"{link}\">رابط المادة</a>")
        return "\n\n".join(lines)

