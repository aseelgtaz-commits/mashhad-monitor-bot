import hashlib
import logging
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup


logger = logging.getLogger("mashhad-monitor.monitor")


class Monitor:
    def __init__(self, db):
        self.db = db

    async def run_once(self, bot):
        sources = self.db.list_sources()

        for source in sources:
            if not source["enabled"]:
                continue

            try:
                items = await self.fetch_source(source["url"])

                for item in items:
                    fingerprint = self.fingerprint(
                        source["id"],
                        item["url"],
                        item["title"],
                    )

                    if self.db.item_exists(fingerprint):
                        continue

                    important = self.is_important(item["title"], item["summary"])

                    inserted = self.db.add_item(
                        source_id=source["id"],
                        title=item["title"],
                        url=item["url"],
                        summary=item["summary"],
                        published_at=item.get("published_at"),
                        fingerprint=fingerprint,
                        is_important=important,
                    )

                    if inserted and important:
                        await self.publish_news(bot, source, item, fingerprint)

                self.db.mark_check_success(source["id"])

            except Exception as exc:
                logger.exception("Source failed: %s", source["name"])
                self.db.mark_check_error(source["id"], exc)

    async def fetch_source(self, url):
        timeout = aiohttp.ClientTimeout(total=20)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; MashhadMonitor/1.0; +monitor)"
            )
        }

        async with aiohttp.ClientSession(
            timeout=timeout,
            headers=headers,
        ) as session:
            async with session.get(url, allow_redirects=True) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").lower()
                body = await response.text(errors="ignore")

        if "xml" in content_type or "<rss" in body[:1000].lower() or "<feed" in body[:1000].lower():
            return self.parse_feed(body)

        return self.parse_webpage(body, url)

    def parse_feed(self, body):
        soup = BeautifulSoup(body, "xml")
        items = []

        for entry in soup.find_all(["item", "entry"])[:50]:
            title = self.clean(entry.find("title").get_text(" ", strip=True) if entry.find("title") else "")
            link_tag = entry.find("link")
            link = ""

            if link_tag:
                link = link_tag.get("href") or link_tag.get_text(" ", strip=True)

            summary_tag = entry.find(["description", "summary", "content"])
            summary = self.clean(
                summary_tag.get_text(" ", strip=True) if summary_tag else ""
            )

            if title and link:
                items.append(
                    {
                        "title": title,
                        "url": link,
                        "summary": summary[:2000],
                        "published_at": None,
                    }
                )

        return items

    def parse_webpage(self, body, base_url):
        soup = BeautifulSoup(body, "html.parser")
        title = self.clean(soup.title.get_text(" ", strip=True) if soup.title else "")
        description = ""

        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            description = self.clean(meta.get("content", ""))

        if not title:
            title = "مادة جديدة من المصدر"

        return [
            {
                "title": title,
                "url": base_url,
                "summary": description[:2000],
                "published_at": None,
            }
        ]

    async def publish_news(self, bot, source, item, fingerprint):
        channel_id = __import__("os").getenv("CHANNEL_ID")

        if not channel_id:
            return

        text = (
            "🛰 *رصد جديد*\n\n"
            f"📰 *{item['title']}*\n\n"
            f"{item['summary']}\n\n"
            f"📡 المصدر: {source['name']}\n"
            f"🔗 {item['url']}"
        )

        await bot.send_message(
            chat_id=channel_id,
            text=text[:4096],
            parse_mode="Markdown",
        )

        self.db.mark_published(fingerprint)

    @staticmethod
    def fingerprint(source_id, url, title):
        raw = f"{source_id}|{url}|{title}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def clean(value):
        return " ".join((value or "").split())

    @staticmethod
    def is_important(title, summary):
        text = f"{title} {summary}".lower()

        keywords = [
            "عاجل",
            "هام",
            "مهم",
            "وفاة",
            "مقتل",
            "انفجار",
            "هجوم",
            "اشتباك",
            "قرار",
            "إعلان",
            "تطور",
            "اتفاق",
            "بيان",
        ]

        return any(word in text for word in keywords)
