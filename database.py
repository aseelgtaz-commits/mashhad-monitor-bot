import sqlite3
import json
import os
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path="mashhad_monitor.db"):
        self.db_path = db_path
        self.init_db()
        self.seed_sources_from_json()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT UNIQUE NOT NULL,
                    enabled INTEGER DEFAULT 1
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER,
                    title TEXT NOT NULL,
                    link TEXT UNIQUE NOT NULL,
                    content TEXT,
                    mahra_score INTEGER DEFAULT 0,
                    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES sources (id)
                )
            """)
            conn.commit()

    def seed_sources_from_json(self):
        """قراءة المصادر من sources.json واستعادتها تلقائياً إذا كانت الداتا بيز فارغة"""
        if os.path.exists("sources.json"):
            try:
                with open("sources.json", "r", encoding="utf-8") as f:
                    sources = json.load(f)
                
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    for src in sources:
                        cursor.execute(
                            "INSERT OR IGNORE INTO sources (name, url) VALUES (?, ?)",
                            (src["name"], src["url"])
                        )
                    conn.commit()
                logger.info("تمت استعادة المصادر بنجاح من ملف sources.json")
            except Exception as e:
                logger.error(f"خطأ أثناء قراءة sources.json: {e}")

    def add_source(self, name: str, url: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO sources (name, url) VALUES (?, ?)", (name, url))
            conn.commit()
            return cursor.lastrowid

    def list_sources(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, url, enabled FROM sources ORDER BY id ASC")
            return [dict(row) for row in cursor.fetchall()]

    def remove_source(self, source_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            conn.commit()

    def dashboard_stats(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sources")
            total_sources = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM sources WHERE enabled = 1")
            enabled_sources = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM items WHERE date(published_at) = date('now')")
            items_today = cursor.fetchone()[0]

            return {
                "sources": total_sources,
                "enabled_sources": enabled_sources,
                "items_today": items_today,
                "published_today": items_today
            }

    def save_item(self, source_id: int, title: str, link: str, content: str, mahra_score: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO items (source_id, title, link, content, mahra_score)
                    VALUES (?, ?, ?, ?, ?)
                """, (source_id, title, link, content, mahra_score))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_today_items(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT i.title, i.link, i.content, i.mahra_score, s.name as source_name
                FROM items i
                JOIN sources s ON i.source_id = s.id
                WHERE date(i.published_at) = date('now')
                ORDER BY i.id DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def build_daily_report(self) -> str:
        items = self.get_today_items()
        sources = self.list_sources()
        enabled_count = sum(1 for s in sources if s["enabled"])

        report = [
            "🛰 <b>التقرير اليومي لرصد المهرة</b>",
            f"📡 <b>المصادر النشطة:</b> {enabled_count}",
            f"📰 <b>المواد المرصودة اليوم:</b> {len(items)}\n",
            "━━━━━━━━━━━━━━━━━━━━",
            "🔴 <b>أبرز مستجدات المهرة المرصودة</b>",
            "━━━━━━━━━━━━━━━━━━━━\n"
        ]

        if not items:
            report.append("لم يتم رصد أخبار أو مستجدات متعلقة بمحافظة المهرة اليوم.")
        else:
            for idx, item in enumerate(items, 1):
                report.append(
                    f"<b>{idx}. {item['title']}</b>\n"
                    f"🔹 <b>المصدر:</b> {item['source_name']}\n"
                    f"🔗 <a href='{item['link']}'>رابط الخبر</a>\n"
                )

        return "\n".join(report)
