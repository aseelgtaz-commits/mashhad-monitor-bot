import logging
from urllib.parse import urljoin

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from mahra_filter import calculate_mahra_score, SCORE_THRESHOLD

logger = logging.getLogger(__name__)


class NewsMonitor:
    def __init__(self, db, channel_id=None):
        self.db = db
        self.channel_id = channel_id

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36 MashhadMonitor/2.0"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    async def fetch_url(self, session: aiohttp.ClientSession, url: str) -> str | None:
        try:
            timeout = aiohttp.ClientTimeout(total=20, connect=8, sock_read=15)
            async with session.get(url, headers=self._headers(), timeout=timeout, allow_redirects=True) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                return await response.text(errors="ignore")
        except Exception as exc:
            logger.warning("تعذر جلب المصدر %s: %s", url, exc)
            return None

    def _save_candidate(self, source: dict, title: str, link: str, content: str = "", published_at: str | None = None) -> bool:
        score, matched = calculate_mahra_score(title, content)
        if score < SCORE_THRESHOLD:
            return False
        return self.db.save_item(
            source_id=source["id"],
            title=title,
            link=link,
            content=content[:10000],
            mahra_score=score,
            matched_keywords=matched,
            published_at=published_at,
        )

    async def parse_source(self, session: aiohttp.ClientSession, source: dict) -> dict:
        url = source["url"]
        content = await self.fetch_url(session, url)
        if content is None:
            raise RuntimeError("تعذر تحميل المصدر")

        added = 0
        feed = feedparser.parse(content)
        if feed.entries:
            for entry in feed.entries:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or url).strip()
                summary = (entry.get("summary") or entry.get("description") or "").strip()
                published_at = entry.get("published") or entry.get("updated")
                if title and link and self._save_candidate(source, title, link, summary, published_at):
                    added += 1
            return {"added": added, "mode": "rss"}

        soup = BeautifulSoup(content, "html.parser")
        for a in soup.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 12:
                continue
            link = urljoin(url, a["href"])
            if self._save_candidate(source, title, link):
                added += 1

        return {"added": added, "mode": "html"}

    async def run_once(self) -> dict:
        logger.info("بدء جولة رصد الأخبار...")
        sources = self.db.list_sources(enabled_only=True)
        summary = {"sources": len(sources), "success": 0, "failed": 0, "added": 0}
        timeout = aiohttp.ClientTimeout(total=25, connect=8, sock_read=18)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for source in sources:
                try:
                    result = await self.parse_source(session, source)
                    self.db.mark_source_result(source["id"], True)
                    summary["success"] += 1
                    summary["added"] += result.get("added", 0)
                    logger.info("المصدر [%s] تمت معالجته: %s مواد جديدة", source["name"], result.get("added", 0))
                except Exception as exc:
                    summary["failed"] += 1
                    self.db.mark_source_result(source["id"], False, str(exc))
                    logger.exception("فشل المصدر [%s]", source["name"])

        logger.info("انتهت جولة الرصد: %s", summary)
        return summary

