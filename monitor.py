import logging
import re
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# قائمة الكلمات المفتاحية الشاملة لرصد أخبار المهرة وسقطرى (معدلة ومصححة)
MAHRA_KEYWORDS = [
    # --- المحافظة والمديريات ---
    "المهرة", "الغيطة", "حوف", "قشن", "سيحوت", 
    "شحن", "حصوين", "المسيلة", "حات", "منعر", "سقطرى",

    # --- القبائل والعائلات المهرية ---
    "كلشات", "الحريزي", "الجدحي", "زعبنوت", "الزبيدي", "محامد", "بن محامد", 
    "بلحاف", "بن عفرار", "عفرار", "رعفيت", "قمصيت", 
    "كده", "كدة", "يسهول", "بيت ياسر", "صمودة",

    # --- المنافذ والموانئ والمناطق الحيوية ---
    "منفذ شحن", "منفذ صرفيت", "صرفيت", "منفذ الوديعة", 
    "ميناء نشطون", "نشطون", "ساحل المهرة", "مارينا", "العيس",

    # --- القيادات والشخصيات البارزة ---
    "محمد علي ياسر", "بن ياسر", "راجح باكريت", "باكريت", 
    "علي سالم الحريزي", "توكل كرمان", "عبدالله بن عفرار", "بن سديف",

    # --- المكونات والقوات والجهات الفاعلة ---
    "أحرار المهرة", "درع الوطن", "المجلس التنسيقي للمهرة", 
    "المجلس العام لأبناء المهرة وسقطرى", "المجلس العام لأبناء المهرة", 
    "لجنة الاعتصام السلمي", "لجنة اعتصام المهرة", "اعتصام المهرة", 
    "السلطة المحلية بالمهرة", "شرطة المهرة", 
    "التحالف السعودي", "التحالف السعودي في المهرة", "التحالف في المهرة",

    # --- مصطلحات وأحداث مرتبطة ---
    "بحر العرب", "إعصار المهرة", "منخفض جوي المهرة", "الصيد البحري المهرة"
]

class NewsMonitor:
    def __init__(self, db, channel_id=None):
        self.db = db
        self.channel_id = channel_id

    def calculate_score(self, text: str) -> int:
        if not text:
            return 0
        score = 0
        for kw in MAHRA_KEYWORDS:
            if kw in text:
                score += 1
        return score

    async def fetch_page(self, session, url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        try:
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    return await response.text()
        except Exception as e:
            logger.warning(f"تعذر جلب الرابط {url}: {e}")
        return None

    async def parse_source(self, session, source):
        url = source["url"]
        
        # تخطي روابط منصات التواصل الاجتماعي المباشرة لتجنب الحظر
        if any(domain in url for domain in ["facebook.com", "x.com", "twitter.com", "instagram.com"]):
            return

        html = await self.fetch_page(session, url)
        if not html:
            return

        soup = BeautifulSoup(html, "html.parser")
        links = soup.find_all("a", href=True)

        for a in links:
            title = a.get_text(strip=True)
            link = a["href"]

            if not title or len(title) < 12:
                continue

            if not link.startswith("http"):
                from urllib.parse import urljoin
                link = urljoin(url, link)

            score = self.calculate_score(title)
            if score > 0:
                saved = self.db.save_item(
                    source_id=source["id"],
                    title=title,
                    link=link,
                    content="",
                    mahra_score=score
                )
                if saved:
                    logger.info(f"تم رصد خبر جديد [{title}] بكلمة مفتاحية تطابق المهرة.")

    async def run_once(self, bot=None):
        logger.info("بدء جولة رصد الأخبار...")
        sources = self.db.list_sources()
        async with aiohttp.ClientSession() as session:
            for source in sources:
                if source["enabled"]:
                    await self.parse_source(session, source)
        logger.info("انتهت جولة الرصد.")
