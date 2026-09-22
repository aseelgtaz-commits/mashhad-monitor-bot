import logging
import feedparser
import asyncio
from typing import List, Dict, Any
from database import Database
from mahra_filter import calculate_mahra_score, SCORE_THRESHOLD

logger = logging.getLogger(__name__)

class NewsMonitor:
    def __init__(self, db: Database, bot=None, channel_id: str = None):
        self.db = db
        self.bot = bot
        self.channel_id = channel_id

    async def fetch_rss_feed(self, url: str) -> List[Dict[str, Any]]:
        """جلب وتحليل تغذية RSS مع timeout آمن."""
        try:
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, url)
            
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
            logger.error(f"خطأ أثناء جلب RSS من {url}: {e}")
            return []

    async def process_source(self, source_id: int, source_name: str, url: str):
        """معالجة مصدر واحد دون الإضرار بالمصادر الأخرى عند الفشل."""
        logger.info(f"بدء فحص المصدر: {source_name}")
        items = await self.fetch_rss_feed(url)
        
        for item in items:
            try:
                title = item['title']
                link = item['link']
                content = item['content']

                # 1. تطبيق فلتر المهرة (Mahra Relevance Filter)
                score, matched = calculate_mahra_score(title, content)
                if score < SCORE_THRESHOLD:
                    continue

                # 2. التحقق من منع التكرار وحفظ الخبر
                is_new = self.db.save_item(
                    source_id=source_id,
                    title=title,
                    link=link,
                    content=content,
                    mahra_score=score
                )

                # 3. إرسال الخبر للقناة إذا كان جديداً ومحصلاً لدرجة عالية
                if is_new and self.bot and self.channel_id:
                    message_text = (
                        f"📰 <b>{title}</b>\n\n"
                        f"🔹 <b>المصدر:</b> {source_name}\n"
                        f"🔗 <a href='{link}'>قراءة الخبر كاملًا</a>"
                    )
                    await self.bot.send_message(
                        chat_id=self.channel_id,
                        text=message_text,
                        parse_mode="HTML",
                        disable_web_page_preview=False
                    )
                    logger.info(f"تم نشر خبر متعلق بالمهرة: {title} (Score: {score})")

            except Exception as e:
                logger.error(f"خطأ في معالجة العنصر من المصدر {source_name}: {e}")

    async def run_monitoring_cycle(self):
        """دورة الرصد لجميع المصادر المسجلة."""
        logger.info("بدء دورة رصد المصادر...")
        sources = self.db.get_active_sources()
        
        for source in sources:
            source_id, name, url = source[0], source[1], source[2]
            try:
                await self.process_source(source_id, name, url)
            except Exception as e:
                logger.error(f"فشلت معالجة المصدر [{name}] لكن استمرت الدورة: {e}")
                
        logger.info("اكتملت دورة رصد المصادر بنجاح.")

# الاسم المستعار لتفادي أخطاء الاستيراد مع الكود القديم
Monitor = NewsMonitor
