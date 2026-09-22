import asyncio, logging, os, threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton,InlineKeyboardMarkup,Update
from telegram.ext import ApplicationBuilder,CallbackQueryHandler,CommandHandler,ContextTypes,MessageHandler,filters
from database import Database
from monitor import NewsMonitor
from report_generator import create_daily_report

TZ=ZoneInfo(os.environ.get("TIMEZONE","Asia/Aden"))
REPORT_DIR=os.environ.get("REPORT_DIR","reports")
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",level=logging.INFO)
logger=logging.getLogger("mashhad_monitor")

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bot is alive!")
    def log_message(self,format,*args): return

def health():
    HTTPServer(("0.0.0.0",int(os.environ.get("PORT","10000"))),HealthCheckHandler).serve_forever()
threading.Thread(target=health,daemon=True).start()

db=Database(); monitor=NewsMonitor(db)

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📰 موجز الأخبار الآنية",callback_data="get_today_report"),
         InlineKeyboardButton("📡 شبكة المصادر المعتمدة",callback_data="show_sources")],
        [InlineKeyboardButton("➕ اقتراح مصدر جديد",callback_data="add_source_info"),
         InlineKeyboardButton("⚙️ مؤشرات أداء النظام",callback_data="system_status")]])

def back_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة إلى لوحة التحكم الرئيسية",callback_data="main_menu")]])

async def welcome(update,context):
    text=("🏛 <b>مرحباً بك أستاذ أصيل!</b> 🎙\n\n"
          "أنا <b>مساعدك الذكي لرصد ومتابعة مستجدات محافظة المهرة</b> لحظة بلحظة.\n\n"
          "📌 اختر الخدمة المطلوبة:")
    if update.message: await update.message.reply_text(text,reply_markup=main_menu(),parse_mode="HTML")
    elif update.callback_query: await update.callback_query.edit_message_text(text,reply_markup=main_menu(),parse_mode="HTML")

async def today_report(query):
    now=datetime.now(TZ)
    items=await asyncio.to_thread(db.get_today_items)
    if not items:
        await query.edit_message_text(
            f"📰 <b>موجز الأخبار الآنية</b>\n\n📅 <b>اليوم:</b> <code>{now:%Y-%m-%d}</code>\n"
            f"⏰ <b>حتى:</b> <code>{now:%H:%M}</code>\n\n"
            "ℹ️ لا توجد أخبار منشورة اليوم بتاريخ نشر موثّق حتى هذه اللحظة.",
            reply_markup=back_menu(),parse_mode="HTML")
        return
    await query.edit_message_text(
        f"📰 <b>موجز الأخبار الآنية</b>\n\n📅 <b>اليوم:</b> <code>{now:%Y-%m-%d}</code>\n"
        f"⏰ <b>حتى:</b> <code>{now:%H:%M}</code>\n📰 <b>أخبار اليوم فقط:</b> <code>{len(items)}</code>\n\n"
        "📎 جارٍ تجهيز التقرير بصيغة Word القابلة للتعديل...",
        reply_markup=back_menu(),parse_mode="HTML")
    sources=await asyncio.to_thread(db.list_sources)
    path=await asyncio.to_thread(create_daily_report,items,sources,REPORT_DIR,now)
    with open(path,"rb") as f:
        await query.message.reply_document(document=f,filename=os.path.basename(path),
            caption=f"📑 <b>تقرير رصد المهرة — {now:%Y-%m-%d}</b>\n📰 أخبار اليوم فقط: {len(items)}\n"
                    "⏱ 00:00 حتى وقت الطلب بتوقيت Asia/Aden",parse_mode="HTML")

async def buttons(update,context):
    q=update.callback_query
    if not q:return
    try: await q.answer()
    except Exception: pass
    try:
        if q.data=="main_menu": await welcome(update,context)
        elif q.data=="get_today_report": await today_report(q)
        elif q.data=="add_source_info":
            await q.edit_message_text("➕ <b>طلب إضافة مصدر جديد</b>\n\nأرسل رابط المصدر المقترح للإدارة.",
                                      reply_markup=back_menu(),parse_mode="HTML")
        elif q.data=="show_sources":
            src=await asyncio.to_thread(db.list_sources)
            lines=["📡 <b>شبكة المصادر المعتمدة</b>\n"]
            lines += [f"{i}. <b>{s['name']}</b> — {'🟢 نشط' if s.get('enabled',1) else '🔴 متوقف'}"
                      for i,s in enumerate(src,1)]
            await q.edit_message_text("\n".join(lines),reply_markup=back_menu(),parse_mode="HTML")
        elif q.data=="system_status":
            st=await asyncio.to_thread(db.dashboard_stats)
            await q.edit_message_text(
                "⚙️ <b>مؤشرات أداء النظام</b>\n\n"
                f"📡 المصادر: <code>{st['sources']}</code>\n🟢 النشطة: <code>{st['enabled_sources']}</code>\n"
                f"📰 أخبار اليوم: <code>{st['items_today']}</code>\n⚠️ غير موثقة: <code>{st['unverified_items']}</code>\n"
                f"🕐 التوقيت: <code>{TZ.key}</code>",reply_markup=back_menu(),parse_mode="HTML")
    except Exception:
        logger.exception("خطأ أثناء تنفيذ الزر")
        try: await q.edit_message_text("⚠️ حدث خطأ أثناء تنفيذ الطلب.",reply_markup=back_menu())
        except Exception: pass

async def monitor_job():
    try: await monitor.run_once()
    except Exception: logger.exception("خطأ أثناء دورة الرصد")

async def post_init(app):
    scheduler=AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(monitor_job,"interval",seconds=int(os.environ.get("CHECK_INTERVAL_SECONDS","300")),
                      max_instances=1,coalesce=True,id="monitoring",replace_existing=True)
    scheduler.start()
    asyncio.create_task(monitor_job())

def main():
    token=os.environ.get("BOT_TOKEN")
    if not token: raise RuntimeError("BOT_TOKEN غير مضبوط في متغيرات البيئة")
    app=ApplicationBuilder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler("start",welcome))
    app.add_handler(CommandHandler("report",welcome))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.Regex(r"^(مرحبا|مرحباً|السلام عليكم|سلام|هلو|أهلا|اهلا|hello|hi)$") | (filters.TEXT & ~filters.COMMAND),welcome))
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()

