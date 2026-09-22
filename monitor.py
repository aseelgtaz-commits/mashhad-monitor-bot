import logging
import feedparser
import asyncio
import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from database import Database
from mahra_filter import calculate_mahra_score, SCORE_THRESHOLD

logger = logging.getLogger(__name__)

class NewsMonitor:
    def __init__(self, db: Database, channel_id: str = None):
        self.db = db
        self.channel_id = channel_id

    def convert_url_if_social(self, url: str) -> str:
        """تحويل روابط X و Facebook لروابط قابلة للرصد برمجياً"""
        # تحويل روابط منصة X (تويتر) إلى تغذية RSS عبر نيتير
        if "x.com/" in url or "twitter.com/" in url:
            username = url.split("/")[-1].split("?")[0]
            return f"https://nitter.net/{username}/rss"
        return url

    async def fetch_facebook_posts(self, url: str) -> List[Dict[str, Any]]:
        """جلب المنشورات العامة من صفحات الفيس بوك"""
        items = []
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: requests.get(url, headers=headers, timeout=10))
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # استخراج النصوص العامة للبروفايل
                posts = soup.find_all('p')
                for post in posts[:5]:
                    text = post.get_text().strip()
                    if len(text) > 20:
                        items.append({
                            'title': text[:80] + "...",
                            'link': url,
                            'content': text
                        })
        except Exception as e:
            logger.error(f"خطأ أثناء جلب فيس بوك من {url}: {e}")
        return items

    async def fetch_feed(self, url: str) -> List[Dict[str, Any]]:
        """جلب المحتوى سواء كان RSS أو منصات تواصل"""
        target_url = self.convert_url_if_social(url)
        
        if "facebook.com" in url:
            return await self.fetch_facebook_posts(url)

        try:
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, target_url)
            
            items = []
            for entry in feed.entries:
                title = getattr(entry, 'title', '').strip()
                link = getattr(entry, 'link', '').strip()
                summary = getattr(entry, 'summary', getattr(entry, 'description', '')).strip()
                
                if title and link:
                    items.append({
                        'title': title,
                        'link': link,
                        'content': summary
                    })
            return items
        except Exception as e:
            logger.error(f"خطأ أثناء جلب التغذية من {target_url}: {e}")
            return []

    async def process_source(self, source_id: int, source_name: str, url: str, bot=None):
        logger.info(f"بدء فحص المصدر: {source_name}")
        items = await self.fetch_feed(url)
        
        for item in items:
            try:
                title = item['title']
                link = item['link']
                content = item['content']

                score, matched = calculate_mahra_score(title, content)
                if score < SCORE_THRESHOLD:
                    continue

                is_new = self.db.save_item(
                    source_id=source_id,
                    title=title,
                    link=link,
                    content=content,
                    mahra_score=score
                )

                if is_new and bot and self.channel_id:
                    message_text = (
                        f"📰 <b>{title}</b>\n\n"
                        f"🔹 <b>المصدر:</b> {source_name}\n"
                        f"🔗 <a href='{link}'>قراءة الخبر/المنشور كاملًا</a>"
                    )
                    await bot.send_message(
                        chat_id=self.channel_id,
                        text=message_text,
                        parse_mode="HTML",
                        disable_web_page_preview=False
                    )
                    logger.info(f"تم نشر خبر المهرة: {title} (Score: {score})")

            except Exception as e:
                logger.error(f"خطأ أثناء معالجة عنصر من {source_name}: {e}")

    async def run_once(self, bot=None):
        logger.info("بدء دورة رصد المصادر...")
        sources = self.db.list_sources()
        
        for source in sources:
            source_id, name, url, enabled = source["id"], source["name"], source["url"], source["enabled"]
            if not enabled:
                continue
            try:
                await self.process_source(source_id, name, url, bot=bot)
            except Exception as e:
                logger.error(f"فشل فحص المصدر [{name}]: {e}")
                
        logger.info("اكتملت دورة رصد المصادر بنجاح.")

Monitor = NewsMonitor
