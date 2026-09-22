import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
import aiohttp
import feedparser
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
MAHRA_KEYWORDS = ["المهرة","الغيضة","الغيظة","حوف","قشن","سيحوت","شحن","حصوين",
"المسيلة","حات","منعر","سقطرى","كلشات","الحريزي","الجدحي","زعبنوت","بلحاف",
"بن عفرار","منفذ شحن","منفذ صرفيت","ميناء نشطون","بن ياسر","السلطة المحلية بالمهرة"]
MAX_ARTICLES_PER_SOURCE = 40
CONCURRENCY = 8

def clean(v): return re.sub(r"\s+"," ",v or "").strip()

def parse_dt(v):
    if not v: return None
    v = clean(str(v))
    try:
        d = datetime.fromisoformat(v.replace("Z","+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception: pass
    try:
        d = parsedate_to_datetime(v)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception: return None

def feed_date(entry):
    for k in ("published_parsed","updated_parsed","created_parsed"):
        v=entry.get(k)
        if v:
            try: return datetime(*v[:6],tzinfo=timezone.utc)
            except Exception: pass
    for k in ("published","updated","created"):
        d=parse_dt(entry.get(k))
        if d: return d
    return None

class NewsMonitor:
    def __init__(self, db, channel_id=None):
        self.db=db; self.channel_id=channel_id

    def calculate_score(self,text):
        return sum(1 for k in MAHRA_KEYWORDS if k in (text or ""))

    async def fetch_url(self,session,url):
        try:
            async with session.get(url,headers={"User-Agent":"Mozilla/5.0 MashhadMonitor",
                                                "Accept-Language":"ar,en;q=0.8"},
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status==200: return await r.text(errors="ignore")
                logger.warning("المصدر %s أعاد HTTP %s",url,r.status)
        except Exception as e:
            logger.warning("تعذر الاتصال بـ %s: %s",url,e)
        return None

    def article_date(self,soup):
        for script in soup.find_all("script",type="application/ld+json"):
            try: data=json.loads(script.string or script.get_text())
            except Exception: continue
            objs=data if isinstance(data,list) else [data]
            expanded=[]
            for o in objs:
                expanded.extend(o.get("@graph",[]) if isinstance(o,dict) and isinstance(o.get("@graph"),list) else [o])
            for o in expanded:
                if isinstance(o,dict):
                    for k in ("datePublished","dateCreated","dateModified"):
                        d=parse_dt(o.get(k))
                        if d:return d
        keys={"article:published_time","og:article:published_time","pubdate","publishdate",
              "publish_date","published","date","dc.date","dc.date.issued","datepublished","datePublished"}
        for tag in soup.find_all("meta"):
            key=tag.get("property") or tag.get("name") or tag.get("itemprop") or ""
            if key in keys:
                d=parse_dt(tag.get("content"))
                if d:return d
        for tag in soup.find_all("time"):
            d=parse_dt(tag.get("datetime")) or parse_dt(tag.get_text(" ",strip=True))
            if d:return d
        return None

    def summary(self,soup):
        for a,b in [("meta",{"name":"description"}),("meta",{"property":"og:description"})]:
            t=soup.find(a,b)
            if t and t.get("content"): return clean(t["content"])[:1500]
        art=soup.find("article")
        return clean(art.get_text(" ",strip=True))[:900] if art else ""

    async def parse_article(self,session,url,fallback):
        html=await self.fetch_url(session,url)
        if not html:return None
        soup=BeautifulSoup(html,"html.parser")
        d=self.article_date(soup)
        if not d:return None
        title=fallback
        og=soup.find("meta",property="og:title")
        if og and og.get("content"): title=clean(og["content"])
        elif soup.title:title=clean(soup.title.get_text(" ",strip=True))
        return {"title":title,"link":url,"content":self.summary(soup),"published_at":d}

    async def parse_source(self,session,source):
        content=await self.fetch_url(session,source["url"])
        if not content:return 0
        feed=feedparser.parse(content)
        added=0
        if feed.entries:
            for e in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
                title=clean(e.get("title")); link=e.get("link",source["url"]); d=feed_date(e)
                if not title or not d: continue
                score=self.calculate_score(title+" "+clean(e.get("summary","")))
                if score and self.db.save_item(source["id"],title,link,clean(e.get("summary",""))[:1500],
                                              score,d.astimezone(timezone.utc),True): added+=1
            return added
        soup=BeautifulSoup(content,"html.parser")
        candidates=[]; seen=set()
        for a in soup.find_all("a",href=True):
            title=clean(a.get_text(" ",strip=True)); link=urljoin(source["url"],a["href"])
            if len(title)<12 or not link.startswith(("http://","https://")) or link in seen: continue
            if self.calculate_score(title)<=0: continue
            seen.add(link); candidates.append((title,link))
            if len(candidates)>=MAX_ARTICLES_PER_SOURCE: break
        sem=asyncio.Semaphore(CONCURRENCY)
        async def one(t,l):
            async with sem:
                try:return await self.parse_article(session,l,t)
                except Exception:return None
        articles=[x for x in await asyncio.gather(*(one(t,l) for t,l in candidates)) if x]
        for a in articles:
            score=self.calculate_score(a["title"]+" "+a["content"])
            if score and self.db.save_item(source["id"],a["title"],a["link"],a["content"],score,
                                           a["published_at"].astimezone(timezone.utc),True): added+=1
        return added

    async def run_once(self,bot=None):
        total=0
        async with aiohttp.ClientSession() as session:
            for source in self.db.list_sources():
                if not source["enabled"]: continue
                try:
                    n=await self.parse_source(session,source); total+=n
                    logger.info("المصدر %s: تمت المعالجة، الجديد=%s",source["name"],n)
                except Exception:
                    logger.exception("تم عزل خطأ المصدر %s",source["name"])
        logger.info("انتهت جولة الرصد. إجمالي المواد الجديدة=%s",total)
        return total

