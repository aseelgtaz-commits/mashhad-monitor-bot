import sqlite3
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
                    FOREIGN KEY(source_id) REFERENCES sources(id)
                );

                CREATE INDEX IF NOT EXISTS idx_items_detected
                ON items(detected_at);

                CREATE INDEX IF NOT EXISTS idx_items_source
                ON items(source_id);
                """
            )

    def add_source(self, name, url):
        with self.connect() as conn:
            exists = conn.execute(
                "SELECT id FROM sources WHERE url = ?", (url,)
            ).fetchone()
            if exists:
                raise ValueError("هذا المصدر موجود مسبقاً.")
            cur = conn.execute(
                """
                INSERT INTO sources(name, url, enabled, created_at)
                VALUES (?, ?, 1, ?)
                """,
                (name, url, now_iso()),
            )
            return cur.lastrowid

    def list_sources(self):
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM sources ORDER BY id"
            ).fetchall()

    def remove_source(self, source_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM items WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    def sources_with_errors(self):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM sources
                WHERE last_error IS NOT NULL
                ORDER BY error_count DESC, id
                """
            ).fetchall()

    def mark_check_success(self, source_id):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sources
                SET last_checked = ?, last_success = ?,
                    last_error = NULL, error_count = 0
                WHERE id = ?
                """,
                (now_iso(), now_iso(), source_id),
            )

    def mark_check_error(self, source_id, error):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sources
                SET last_checked = ?, last_error = ?,
                    error_count = error_count + 1
                WHERE id = ?
                """,
                (now_iso(), str(error)[:1000], source_id),
            )

    def item_exists(self, fingerprint):
        with self.connect() as conn:
            return conn.execute(
                "SELECT 1 FROM items WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone() is not None

    def add_item(
        self,
        source_id,
        title,
        url,
        summary,
        published_at,
        fingerprint,
        is_important=False,
    ):
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO items(
                        source_id, title, url, summary, published_at,
                        detected_at, fingerprint, is_important
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        title,
                        url,
                        summary,
                        published_at,
                        now_iso(),
                        fingerprint,
                        int(is_important),
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def mark_published(self, fingerprint):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE items
                SET published_to_channel = 1
                WHERE fingerprint = ?
                """,
                (fingerprint,),
            )

    def dashboard_stats(self):
        with self.connect() as conn:
            sources = conn.execute(
                "SELECT COUNT(*) FROM sources"
            ).fetchone()[0]
            enabled = conn.execute(
                "SELECT COUNT(*) FROM sources WHERE enabled = 1"
            ).fetchone()[0]
            items_today = conn.execute(
                """
                SELECT COUNT(*) FROM items
                WHERE date(detected_at) = date('now')
                """
            ).fetchone()[0]
            published_today = conn.execute(
                """
                SELECT COUNT(*) FROM items
                WHERE published_to_channel = 1
                AND date(detected_at) = date('now')
                """
            ).fetchone()[0]
            return {
                "sources": sources,
                "enabled_sources": enabled,
                "items_today": items_today,
                "published_today": published_today,
            }

    def build_daily_report(self):
        # SQLite dates are stored in UTC. The report is a first stable version;
        # timezone-aware daily grouping will be refined with the final schema.
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT i.*, s.name AS source_name
                FROM items i
                JOIN sources s ON s.id = i.source_id
                WHERE date(i.detected_at) = date('now')
                ORDER BY i.detected_at DESC
                """
            ).fetchall()

            sources = conn.execute(
                "SELECT * FROM sources ORDER BY id"
            ).fetchall()

        lines = [
            "🛰 *تقرير الرصد اليومي*",
            "",
            "📅 آخر 24 ساعة من المواد التي رصدها النظام",
            "",
            f"📡 المصادر: {len(sources)}",
            f"📰 المواد المرصودة: {len(rows)}",
            f"📢 المنشورة في القناة: "
            f"{sum(1 for r in rows if r['published_to_channel'])}",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "🔴 *أبرز المواد المرصودة*",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        if not rows:
            lines.append("لم يتم رصد مواد جديدة خلال الفترة.")
        else:
            for i, row in enumerate(rows[:30], 1):
                title = row["title"] or "مادة بدون عنوان"
                lines.extend(
                    [
                        f"{i}. *{title}*",
                        f"📡 المصدر: {row['source_name']}",
                        f"🔗 {row['url']}",
                        "",
                    ]
                )

        lines.extend(
            [
                "━━━━━━━━━━━━━━━━━━━━",
                "📡 *تفاصيل المصادر*",
                "━━━━━━━━━━━━━━━━━━━━",
                "",
            ]
        )

        for source in sources:
            status = "🟢" if not source["last_error"] else "🔴"
            lines.append(
                f"{status} *{source['name']}* — "
                f"{source['error_count']} أخطاء مسجلة"
            )

        return "\n".join(lines)
