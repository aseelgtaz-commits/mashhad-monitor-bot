import asyncio
import logging
from urllib.parse import urljoin

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from mahra_filter import SCORE_THRESHOLD, calculate_mahra_score

logger = logging.getLogger(__name__)


class NewsMonitor:
    def __init__(self, db, request_timeout: int = 20):
        self.db = db
        self.request_timeout = request_timeout

    async def fetch_url(self, session: aiohttp.ClientSession, url: str) -> str | None:
        headers = {
            "User-Agent": "MashhadMonitor/3.0 (+https://t.me/) Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
                return await response.text(errors="ignore")
        except Exception as exc:
            logger.warning("تعذر جلب %s: %s", url, exc)
            raise

    @staticmethod
    def _entry_date(entry):
        for key in ("published", "updated", "created"):
            value = entry.get(key)
            if value:
                return str(value)
        return None

    async def parse_source(self, session, source):
        content = await self.fetch_url(session, source["url"])
        feed = feedparser.parse(content)
        saved = 0

        if feed.entries:
            for entry in feed.entries[:200]:
                title = str(entry.get("title", "")).strip()
                link = str(entry.get("link", source["url"])).strip()
                summary = str(entry.get("summary", entry.get("description", ""))).strip()
                score, keywords = calculate_mahra_score(title, BeautifulSoup(summary, "html.parser").get_text(" ", strip=True))
                if score < SCORE_THRESHOLD:
                    continue
                if await asyncio.to_thread(
                    self.db.save_item,
                    source["id"], title, link, summary, score, keywords, self._entry_date(entry)
                ):
                    saved += 1
            return saved

        soup = BeautifulSoup(content, "html.parser")
        for anchor in soup.find_all("a", href=True)[:500]:
            title = anchor.get_text(" ", strip=True)
            if len(title) < 12:
                continue
            link = urljoin(source["url"], anchor["href"])
            score, keywords = calculate_mahra_score(title, "")
            if score < SCORE_THRESHOLD:
                continue
            if await asyncio.to_thread(self.db.save_item, source["id"], title, link, "", score, keywords, None):
                saved += 1
        return saved

    async def run_once(self):
        logger.info("بدء جولة رصد الأخبار...")
        sources = await asyncio.to_thread(self.db.list_sources)
        connector = aiohttp.TCPConnector(limit=10, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            for source in sources:
                if not source.get("enabled", True):
                    continue
                try:
                    count = await self.parse_source(session, source)
                    await asyncio.to_thread(self.db.mark_source_result, source["id"], True, None)
                    logger.info("المصدر %s: تمت المعالجة، الجديد=%s", source["name"], count)
                except Exception as exc:
                    await asyncio.to_thread(self.db.mark_source_result, source["id"], False, str(exc))
                    logger.exception("فشل المصدر %s", source["name"])
        logger.info("انتهت جولة الرصد.")

