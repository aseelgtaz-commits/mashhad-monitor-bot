import sqlite3
import hashlib
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path="mashhad_monitor.db"):
        self.path = path
        self._init()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_checked TEXT,
                    last_success TEXT,
                    last_error TEXT,
                    error_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL,
                    title TEXT,
                    url TEXT NOT NULL,
                    summary TEXT,
                    published_at TEXT,
                    detected_at TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    is_important INTEGER NOT NULL DEFAULT 0,
                    published_to_channel INTEGER NOT NULL DEFAULT 0,
                    mahra_score INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(source_id) REFERENCES sources(id)
                );

                CREATE INDEX IF NOT EXISTS idx_items_detected ON items(detected_at);
                CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_id);
                """
            )
            # إضافة عمود mahra_score للقواعد القديمة إن لم يكن موجوداً
            try:
                conn.execute("ALTER TABLE items ADD COLUMN mahra_score INTEGER NOT NULL DEFAULT 0;")
            except sqlite3.OperationalError:
                pass  # العمود موجود بالفعل

    def add_source(self, name, url):
        with self.connect() as conn:
            exists = conn.execute("SELECT id FROM sources WHERE url = ?", (url,)).fetchone()
            if exists:
                raise ValueError("هذا المصدر موجود مسبقاً.")
            cur = conn.execute(
                "INSERT INTO sources(name, url, enabled, created_at) VALUES (?, ?, 1, ?)",
                (name, url, now_iso()),
            )
            return cur.lastrowid

    def list_sources(self):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM sources ORDER BY id").fetchall()

    def remove_source(self, source_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM items WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    def save_item(self, source_id, title, link, content, mahra_score=0):
        """حفظ الخبر مع التأكد من عدم التكرار بواسطة Hash fingerprint"""
        raw_fingerprint = f"{link}-{title}".encode('utf-8')
        fingerprint = hashlib.md5(raw_fingerprint).hexdigest()

        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO items(source_id, title, url, summary, detected_at, fingerprint, mahra_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (source_id, title, link, content, now_iso(), fingerprint, mahra_score)
                )
                return True
            except sqlite3.IntegrityError:
                return False  # الخبر موجود مسبقاً

    def get_today_mahra_items(self):
        """استرجاع الأخبار الخاصة بالمهرة والمستخرجة اليوم"""
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT i.title, s.name as source_name, i.url, i.mahra_score, i.detected_at
                FROM items i
                JOIN sources s ON s.id = i.source_id
                WHERE date(i.detected_at) = date('now')
                ORDER BY i.detected_at DESC
                """
            ).fetchall()

    def dashboard_stats(self):
        with self.connect() as conn:
            sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            enabled = conn.execute("SELECT COUNT(*) FROM sources WHERE enabled = 1").fetchone()[0]
            items_today = conn.execute("SELECT COUNT(*) FROM items WHERE date(detected_at) = date('now')").fetchone()[0]
            published_today = conn.execute("SELECT COUNT(*) FROM items WHERE published_to_channel = 1 AND date(detected_at) = date('now')").fetchone()[0]
            return {
                "sources": sources,
                "enabled_sources": enabled,
                "items_today": items_today,
                "published_today": published_today,
            }

    def build_daily_report(self):
        rows = self.get_today_mahra_items()
        sources = self.list_sources()

        lines = [
            "🛰 <b>التقرير اليومي لرصد المهرة</b>",
            f"📅 <b>التاريخ:</b> {datetime.now().strftime('%Y-%m-%d')}",
            "",
            f"📡 <b>المصادر النشطة:</b> {len(sources)}",
            f"📰 <b>المواد المرصودة اليوم:</b> {len(rows)}",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "🔴 <b>أبرز مستجدات المهرة المرصودة</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        if not rows:
            lines.append("لم يتم رصد أخبار أو مستجدات متعلقة بمحافظة المهرة اليوم.")
        else:
            for i, row in enumerate(rows[:25], 1):
                title = row["title"] or "خبر بدون عنوان"
                lines.extend([
                    f"{i}️⃣ <b>{title}</b>",
                    f"   📍 <b>المصدر:</b> {row['source_name']}",
                    f"   🔗 <a href='{row['url']}'>رابط الخبر</a>",
                    "",
                ])

        return "\n".join(lines)
