import asyncio
import logging
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from database import Database
from monitor import NewsMonitor
from report_generator import create_daily_report

TIMEZONE_NAME = os.environ.get("TIMEZONE", "Asia/Aden")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "300"))
REPORT_HOUR = int(os.environ.get("REPORT_HOUR", "0"))
REPORT_MINUTE = int(os.environ.get("REPORT_MINUTE", "0"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
DATABASE_PATH = os.environ.get("DATABASE_PATH", "mashhad_monitor.db")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("mashhad_monitor")


def get_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📰 إنشاء موجز Word", callback_data="get_today_report"),
         InlineKeyboardButton("📡 شبكة المصادر", callback_data="show_sources")],
        [InlineKeyboardButton("➕ اقتراح مصدر", callback_data="add_source_info"),
         InlineKeyboardButton("⚙️ حالة النظام", callback_data="system_status")],
    ])


def get_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة إلى لوحة التحكم", callback_data="main_menu")]])


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Mashhad Monitor is alive")

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info("Health server listening on port %s", port)
    server.serve_forever()


db = Database(DATABASE_PATH, TIMEZONE_NAME)
monitor = NewsMonitor(db)
monitor_lock: asyncio.Lock | None = None
scheduler: AsyncIOScheduler | None = None


async def welcome_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🏛 <b>مرحباً بك في مرصد المشهد الشرقي</b>\n\n"
        "نظام رصد ومتابعة للمصادر الإخبارية، مع إمكانية إنشاء موجز احترافي بصيغة Word قابل للتحرير.\n\n"
        "📌 اختر الخدمة المطلوبة من لوحة التحكم:"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
        except Exception:
            logger.exception("فشل عرض القائمة الرئيسية")


async def send_word_report(chat_id: int, context: ContextTypes.DEFAULT_TYPE, caption: str):
    path = None
    try:
        path = await asyncio.to_thread(create_daily_report, db, TIMEZONE_NAME)
        with open(path, "rb") as file_handle:
            await context.bot.send_document(
                chat_id=chat_id,
                document=file_handle,
                caption=caption,
            )
    finally:
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                logger.warning("تعذر حذف ملف التقرير المؤقت: %s", path)


async def handle_button_clicks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    logger.info("CALLBACK RECEIVED: %s", query.data)
    try:
        await query.answer()
        logger.info("CALLBACK ANSWERED: %s", query.data)
    except Exception:
        logger.exception("فشل answerCallbackQuery")

    try:
        if query.data == "main_menu":
            await welcome_user(update, context)
            return

        if query.data == "get_today_report":
            await query.edit_message_text(
                "⏳ <b>جارٍ إعداد موجز Word...</b>\n\nسيتم إرسال الملف هنا بعد اكتمال تجهيزه.",
                parse_mode="HTML",
            )
            items = await asyncio.to_thread(db.get_today_items)
            caption = (
                "📄 <b>الموجز الإخباري الشامل</b>\n"
                f"📅 {datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M')} بتوقيت عدن\n"
                f"📰 عدد المواد: {len(items)}\n\n"
                "الملف قابل للتحرير بالكامل في Microsoft Word."
            )
            await send_word_report(query.message.chat_id, context, caption)
            await query.message.reply_text("✅ تم إنشاء الموجز بنجاح.", reply_markup=get_back_keyboard(), parse_mode="HTML")
            return

        if query.data == "show_sources":
            sources = await asyncio.to_thread(db.list_sources)
            lines = ["📡 <b>شبكة المصادر المعتمدة</b>", ""]
            if not sources:
                lines.append("لا توجد مصادر مسجلة.")
            else:
                for index, source in enumerate(sources, 1):
                    status = "🟢" if source.get("consecutive_errors", 0) == 0 else "🔴"
                    lines.append(f"{index}. {status} <b>{source['name']}</b>")
            await query.edit_message_text("\n".join(lines), reply_markup=get_back_keyboard(), parse_mode="HTML")
            return

        if query.data == "add_source_info":
            await query.edit_message_text(
                "➕ <b>اقتراح مصدر جديد</b>\n\nأرسل رابط الموقع أو المصدر إلى إدارة النظام لإضافته إلى خطة الرصد.",
                reply_markup=get_back_keyboard(), parse_mode="HTML",
            )
            return

        if query.data == "system_status":
            stats = await asyncio.to_thread(db.dashboard_stats)
            text = (
                "⚙️ <b>حالة النظام</b>\n\n"
                f"📡 المصادر: <code>{stats['sources']}</code>\n"
                f"🟢 المصادر النشطة: <code>{stats['enabled_sources']}</code>\n"
                f"📰 مواد اليوم: <code>{stats['items_today']}</code>\n"
                f"🔴 مصادر بها أخطاء: <code>{stats['source_errors']}</code>\n"
                f"🕐 المنطقة الزمنية: <code>{TIMEZONE_NAME}</code>"
            )
            await query.edit_message_text(text, reply_markup=get_back_keyboard(), parse_mode="HTML")
            return

    except Exception as exc:
        logger.exception("BUTTON ERROR [%s]", query.data)
        try:
            await query.message.reply_text("⚠️ حدث خطأ أثناء تنفيذ الطلب. تم تسجيل التفاصيل في سجل النظام.", reply_markup=get_back_keyboard())
        except Exception:
            logger.exception("فشل إرسال رسالة الخطأ للمستخدم")


async def run_periodic_monitoring():
    global monitor_lock
    if monitor_lock is None:
        monitor_lock = asyncio.Lock()
    if monitor_lock.locked():
        logger.warning("تم تخطي جولة رصد لأن جولة سابقة ما زالت تعمل.")
        return
    async with monitor_lock:
        try:
            await monitor.run_once()
        except Exception:
            logger.exception("خطأ غير متوقع في دورة الرصد")


async def send_daily_report(application):
    if not CHANNEL_ID:
        logger.warning("CHANNEL_ID غير مضبوط؛ لن يتم إرسال التقرير اليومي.")
        return
    try:
        path = await asyncio.to_thread(create_daily_report, db, TIMEZONE_NAME)
        try:
            with open(path, "rb") as file_handle:
                await application.bot.send_document(
                    chat_id=CHANNEL_ID,
                    document=file_handle,
                    caption=f"📄 الموجز الإخباري اليومي — {datetime.now(TIMEZONE).strftime('%Y-%m-%d')}",
                )
        finally:
            Path(path).unlink(missing_ok=True)
    except Exception:
        logger.exception("فشل إرسال التقرير اليومي")


async def post_init(application):
    global scheduler, monitor_lock
    monitor_lock = asyncio.Lock()
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(run_periodic_monitoring, "interval", seconds=CHECK_INTERVAL_SECONDS, id="monitor", max_instances=1, coalesce=True)
    scheduler.add_job(send_daily_report, "cron", hour=REPORT_HOUR, minute=REPORT_MINUTE, args=[application], id="daily_report", max_instances=1)
    scheduler.start()
    application.create_task(run_periodic_monitoring())
    logger.info("تم تشغيل النظام — timezone=%s interval=%ss", TIMEZONE_NAME, CHECK_INTERVAL_SECONDS)


async def post_shutdown(application):
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)


def error_handler(update, context):
    logger.exception("Unhandled update error", exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير مضبوط في Environment Variables")
    threading.Thread(target=run_health_server, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("start", welcome_user))
    app.add_handler(CommandHandler("report", welcome_user))
    app.add_handler(CallbackQueryHandler(handle_button_clicks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, welcome_user))
    app.add_error_handler(error_handler)
    logger.info("بدء تشغيل Mashhad Monitor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, close_loop=True)


if __name__ == "__main__":
    main()

