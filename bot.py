import asyncio
import html
import logging
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import Database
from monitor import NewsMonitor

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger("mashhad_monitor")

TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Aden")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
CHECK_INTERVAL_SECONDS = max(60, int(os.getenv("CHECK_INTERVAL_SECONDS", "300")))
REPORT_HOUR = int(os.getenv("REPORT_HOUR", "0"))
REPORT_MINUTE = int(os.getenv("REPORT_MINUTE", "0"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()

_db = Database(os.getenv("DATABASE_PATH", "mashhad_monitor.db"), TIMEZONE_NAME)
_monitor = NewsMonitor(_db, CHANNEL_ID or None)
_monitor_lock = asyncio.Lock()
_scheduler: AsyncIOScheduler | None = None


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Mashhad Monitor Bot is alive")

    def log_message(self, format, *args):
        return


def start_health_server() -> None:
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info("Health server listening on port %s", port)
    server.serve_forever()


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📰 موجز الأخبار الآنية", callback_data="get_today_report"),
            InlineKeyboardButton("📡 شبكة المصادر", callback_data="show_sources"),
        ],
        [
            InlineKeyboardButton("➕ اقتراح مصدر", callback_data="add_source_info"),
            InlineKeyboardButton("⚙️ حالة النظام", callback_data="system_status"),
        ],
    ])


def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للرئيسية", callback_data="main_menu")]])


WELCOME_TEXT = (
    "🏛 <b>مرحباً بك أستاذ أصيل!</b> 🎙\n\n"
    "أنا <b>مساعدك الذكي لرصد ومتابعة مستجدات محافظة المهرة</b> لحظة بلحظة.\n"
    "أتابع المصادر المسجلة وأجمع المواد المرتبطة بالمهرة في قاعدة بيانات واحدة.\n\n"
    "📌 <b>اختر الخدمة المطلوبة من لوحة التحكم:</b>"
)


async def welcome_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(WELCOME_TEXT, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
        return
    if update.callback_query:
        await update.callback_query.edit_message_text(
            WELCOME_TEXT,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )


async def _safe_edit(query, text: str, reply_markup=None) -> None:
    try:
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return
        raise


async def handle_button_clicks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    data = query.data or ""
    logger.info("CALLBACK RECEIVED | id=%s | data=%s | user=%s", query.id, data, query.from_user.id if query.from_user else "?")

    # يجب أن تكون الإجابة على callback هي أول عملية Telegram تقريباً.
    await query.answer()
    logger.info("CALLBACK ANSWERED | id=%s | data=%s", query.id, data)

    try:
        if data == "main_menu":
            await welcome_user(update, context)
            return

        if data == "add_source_info":
            await _safe_edit(
                query,
                "➕ <b>طلب إضافة مصدر جديد للشبكة</b>\n\nأرسل رابط المصدر المقترح للإدارة لإضافته إلى خطة الرصد.",
                get_back_keyboard(),
            )
            return

        if data == "show_sources":
            sources = await asyncio.to_thread(_db.list_sources)
            lines = ["📡 <b>قائمة المصادر المعتمدة للرصد</b>", ""]
            if not sources:
                lines.append("لا توجد مصادر مسجلة حالياً.")
            else:
                for idx, source in enumerate(sources, 1):
                    status = "🟢 نشط" if source["enabled"] else "🔴 متوقف"
                    error_note = " ⚠️" if source.get("consecutive_errors", 0) else ""
                    lines.append(f"<b>{idx}. {html.escape(source['name'])}</b> | {status}{error_note}")
            await _safe_edit(query, "\n".join(lines), get_back_keyboard())
            return

        if data == "system_status":
            stats = await asyncio.to_thread(_db.dashboard_stats)
            text = (
                "⚙️ <b>مؤشرات تشغيل النظام</b>\n\n"
                f"📡 إجمالي المصادر: <code>{stats['sources']}</code>\n"
                f"🟢 المصادر النشطة: <code>{stats['enabled_sources']}</code>\n"
                f"📰 المواد المرصودة اليوم: <code>{stats['items_today']}</code>\n"
                f"⚠️ مصادر بها أخطاء: <code>{stats['sources_with_errors']}</code>\n"
                f"⏰ التوقيت: <code>{html.escape(TIMEZONE_NAME)}</code>\n"
                f"🔄 الفحص الدوري: كل <code>{CHECK_INTERVAL_SECONDS}</code> ثانية"
            )
            await _safe_edit(query, text, get_back_keyboard())
            return

        if data == "get_today_report":
            items = await asyncio.to_thread(_db.get_today_items, 50)
            now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d | %I:%M:%S %p")
            lines = [
                "📰 <b>الموجز الإخباري الخاص باليوم</b>",
                f"⏱ <b>وقت الاستعلام:</b> <code>{now_str}</code>",
                f"📊 <b>عدد المواد:</b> <code>{len(items)}</code>",
                "───────────────────",
            ]
            if not items:
                lines.append("ℹ️ لم يتم تسجيل مستجدات مرتبطة بالمهرة حتى الآن.")
            else:
                for idx, item in enumerate(items, 1):
                    title = html.escape(item.get("title", "بدون عنوان"))
                    source = html.escape(item.get("source_name") or "مصدر غير معروف")
                    link = html.escape(item.get("link") or "#", quote=True)
                    lines.append(f"<b>{idx}. {title}</b>\n🔹 <b>المصدر:</b> {source}\n🔗 <a href=\"{link}\">المادة الكاملة</a>")
            await _safe_edit(query, "\n\n".join(lines), get_back_keyboard())
            return

        logger.warning("Unknown callback_data received: %s", data)
        await _safe_edit(query, "⚠️ هذا الخيار غير معروف أو لم يعد متاحاً.", get_back_keyboard())

    except Exception:
        logger.exception("CALLBACK FAILED | id=%s | data=%s", query.id, data)
        try:
            await query.edit_message_text(
                "⚠️ حدث خطأ أثناء تنفيذ الطلب. تم تسجيل التفاصيل في سجل النظام.",
                reply_markup=get_back_keyboard(),
            )
        except Exception:
            logger.exception("تعذر عرض رسالة الخطأ للمستخدم")


async def run_periodic_monitoring() -> None:
    if _monitor_lock.locked():
        logger.warning("تم تخطي دورة الرصد: الدورة السابقة ما زالت تعمل")
        return
    async with _monitor_lock:
        try:
            summary = await _monitor.run_once()
            logger.info("MONITOR CYCLE COMPLETE | %s", summary)
        except Exception:
            logger.exception("MONITOR CYCLE FAILED")


async def send_daily_report(application: Application) -> None:
    if not CHANNEL_ID:
        logger.warning("CHANNEL_ID غير مضبوط؛ تم تخطي التقرير اليومي")
        return
    try:
        report = await asyncio.to_thread(_db.build_daily_report, 50)
        await application.bot.send_message(
            chat_id=CHANNEL_ID,
            text=report,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info("DAILY REPORT SENT")
    except TelegramError:
        logger.exception("فشل إرسال التقرير اليومي إلى القناة")
    except Exception:
        logger.exception("DAILY REPORT FAILED")


async def post_init(application: Application) -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    _scheduler.add_job(
        run_periodic_monitoring,
        "interval",
        seconds=CHECK_INTERVAL_SECONDS,
        id="monitoring",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        send_daily_report,
        "cron",
        hour=REPORT_HOUR,
        minute=REPORT_MINUTE,
        args=[application],
        id="daily_report",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Scheduler started | interval=%ss | daily=%02d:%02d %s", CHECK_INTERVAL_SECONDS, REPORT_HOUR, REPORT_MINUTE, TIMEZONE_NAME)

    # دورة أولية بعد بدء التطبيق، حتى لا ننتظر 5 دقائق لأول فحص.
    application.create_task(run_periodic_monitoring(), name="initial-monitoring")


async def post_shutdown(application: Application) -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("UNHANDLED UPDATE ERROR | update=%r", update, exc_info=context.error)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير مضبوط في Environment Variables")

    threading.Thread(target=start_health_server, daemon=True, name="render-health-server").start()

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    greeting_patterns = r"^(مرحبا|مرحباً|السلام عليكم|سلام|هلو|أهلا|اهلا|hello|hi)$"

    application.add_handler(CommandHandler("start", welcome_user))
    application.add_handler(CommandHandler("report", welcome_user))
    application.add_handler(CallbackQueryHandler(handle_button_clicks))
    application.add_handler(
        MessageHandler(
            filters.Regex(greeting_patterns) & ~filters.COMMAND,
            welcome_user,
        )
    )
    application.add_error_handler(error_handler)

    logger.info("Mashhad Monitor Bot starting | PTB=%s | Python=%s", __import__("telegram").__version__, __import__("sys").version.split()[0])
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=True,
    )


if __name__ == "__main__":
    main()

