import logging
from urllib.parse import urljoin
import aiohttp
from bs4 import BeautifulSoup
import feedparser

logger = logging.getLogger(__name__)

MAHRA_KEYWORDS = [
    "المهرة",
    "الغيضة",
    "الغيظة",
    "حوف",
    "قشن",
    "سيحوت",
    "شحن",
    "حصوين",
    "المسيلة",
    "حات",
    "منعر",
    "سقطرى",
    "كلشات",
    "الحريزي",
    "الجدحي",
    "زعبنوت",
    "بلحاف",
    "بن عفرار",
    "منفذ شحن",
    "منفذ صرفيت",
    "ميناء نشطون",
    "بن ياسر",
    "السلطة المحلية بالمهرة",
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

  async def fetch_url(self, session, url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        )
    }
    try:
      async with session.get(url, headers=headers, timeout=15) as response:
        if response.status == 200:
          return await response.text()
    except Exception as e:
      logger.warning(f"تعذر الاتصال بـ {url}: {e}")
    return None

  async def parse_source(self, session, source):
    url = source["url"]
    content = await self.fetch_url(session, url)
    if not content:
      return

    # 1. محاولة المعالجة كـ RSS / Atom
    feed = feedparser.parse(content)
    if feed.entries:
      for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", url)

        score = self.calculate_score(title)
        if score > 0:
          self.db.save_item(
              source_id=source["id"],
              title=title,
              link=link,
              content="",
              mahra_score=score,
          )
      return

    # 2. المعالجة كصفحة HTML عادية
    soup = BeautifulSoup(content, "html.parser")
    links = soup.find_all("a", href=True)
    for a in links:
      title = a.get_text(strip=True)
      link = a["href"]

      if not title or len(title) < 12:
        continue

      if not link.startswith("http"):
        link = urljoin(url, link)

      score = self.calculate_score(title)
      if score > 0:
        self.db.save_item(
            source_id=source["id"],
            title=title,
            link=link,
            content="",
            mahra_score=score,
        )

  async def run_once(self, bot=None):
    logger.info("بدء جولة رصد الأخبار...")
    sources = self.db.list_sources()
    async with aiohttp.ClientSession() as session:
      for source in sources:
        if source["enabled"]:
          await self.parse_source(session, source)
    logger.info("انتهت جولة الرصد.")
