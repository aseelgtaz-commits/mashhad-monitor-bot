import asyncio
import logging
import os
import threading
from datetime import time
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

from database import Database
from monitor import NewsMonitor

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("mashhad-monitor")

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Aden"))
REPORT_HOUR = int(os.getenv("REPORT_HOUR", "0"))
REPORT_MINUTE = int(os.getenv("REPORT_MINUTE", "0"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))

db = Database(os.getenv("DATABASE_PATH", "mashhad_monitor.db"))


def is_admin(update: Update) -> bool:
    admin_ids = {
        int(x.strip())
        for x in os.getenv("ADMIN_USER_IDS", "").split(",")
        if x.strip().isdigit()
    }
    user = update.effective_user
    return bool(user and user.id in admin_ids)


async def denied(update: Update):
    if update.effective_message:
        await update.effective_message.reply_text("⛔ هذا الأمر متاح للمشرفين فقط.")


async def send_split_message(context: ContextTypes.DEFAULT_TYPE, chat_id: str, text: str, max_length: int = 3800):
    """تقسيم الرسائل لتجنب خطأ Message is too long"""
    if len(text) <= max_length:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
        return

    lines = text.split("\n")
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > max_length:
            await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML", disable_web_page_preview=True)
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML", disable_web_page_preview=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    stats = db.dashboard_stats()
    keyboard = [
        [
            InlineKeyboardButton("➕ إضافة مصدر", callback_data="add_help"),
            InlineKeyboardButton("📡 مصادري", callback_data="sources"),
        ],
        [
            InlineKeyboardButton("📊 تقرير اليوم", callback_data="report"),
        ],
    ]

    text = (
        "🛰 <b>مرحباً بك في Mashhad Monitor</b>\n\n"
        "نظام رصد ومتابعة إخباري متخصص في محافظة المهرة.\n\n"
        f"📡 المصادر: {stats['sources']}\n"
        f"🟢 النشطة: {stats['enabled_sources']}\n"
        f"📰 مواد اليوم: {stats['items_today']}\n"
        f"📢 منشور اليوم: {stats['published_today']}\n\n"
        "من هنا يمكنك إدارة المصادر ومتابعة الرصد."
    )

    if update.message:
        await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    await update.message.reply_text(
        "📚 <b>مساعدة Mashhad Monitor</b>\n\n"
        "➕ إضافة مصدر:\n<code>/add اسم المصدر | الرابط</code>\n\n"
        "📡 عرض المصادر:\n<code>/sources</code>\n\n"
        "🗑 حذف مصدر:\n<code>/remove رقم_المصدر</code>\n\n"
        "📊 التقرير:\n<code>/report</code>",
        parse_mode="HTML",
    )


async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    text = update.message.text.partition(" ")[2].strip()

    if "|" not in text:
        await update.message.reply_text(
            "➕ أرسل المصدر بهذا الشكل:\n<code>/add اسم المصدر | https://example.com</code>",
            parse_mode="HTML",
        )
        return

    name, url = [x.strip() for x in text.split("|", 1)]

    if not name or not url.startswith(("http://", "https://")):
        await update.message.reply_text("❌ اسم المصدر أو الرابط غير صالح.")
        return

    try:
        source_id = db.add_source(name, url)
        await update.message.reply_text(
            f"✅ <b>تمت إضافة المصدر</b>\n\n📡 {name}\n🔗 {url}\n🆔 {source_id}",
            parse_mode="HTML",
        )
    except ValueError as exc:
        await update.message.reply_text(f"⚠️ {exc}")
    except Exception:
        logger.exception("Failed to add source")
        await update.message.reply_text("❌ حدث خطأ أثناء حفظ المصدر.")


async def sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    chat_id = str(update.effective_chat.id)
    rows = db.list_sources()
    if not rows:
        await context.bot.send_message(chat_id=chat_id, text="📡 لا توجد مصادر مضافة حالياً.")
        return

    lines = [f"📡 <b>المصادر المضافة ({len(rows)})</b>\n"]
    for index, row in enumerate(rows, 1):
        status = "🟢 نشط" if row["enabled"] else "⏸ متوقف"
        lines.append(f"{index}. <b>{row['name']}</b>\n   {status}\n   🔗 {row['url']}")

    full_text = "\n\n".join(lines)
    await send_split_message(context, chat_id, full_text)


async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    text = update.message.text.partition(" ")[2].strip()
    try:
        number = int(text)
    except ValueError:
        await update.message.reply_text("استخدم: <code>/remove 1</code>", parse_mode="HTML")
        return

    rows = db.list_sources()
    if number < 1 or number > len(rows):
        await update.message.reply_text("❌ رقم المصدر غير صحيح.")
        return

    row = rows[number - 1]
    db.remove_source(row["id"])
    await update.message.reply_text(f"🗑 تم حذف المصدر: <b>{row['name']}</b>", parse_mode="HTML")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    report = db.build_daily_report()
    await send_split_message(context, str(update.effective_chat.id), report)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        await query.message.reply_text("⛔ غير مصرح.")
        return

    if query.data == "add_help":
        await query.message.reply_text("➕ أرسل:\n<code>/add اسم المصدر | https://example.com</code>", parse_mode="HTML")
    elif query.data == "sources":
        await sources(update, context)
    elif query.data == "report":
        await report_command(update, context)


async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    monitor = context.application.bot_data["monitor"]
    try:
        await monitor.run_once(context.application.bot)
    except Exception:
        logger.exception("Monitor cycle failed")


async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    report = db.build_daily_report()
    if CHANNEL_ID:
        try:
            await send_split_message(context, CHANNEL_ID, report)
            logger.info("Daily report sent to channel")
        except Exception:
            logger.exception("Failed to send daily report to channel")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        return


def run_web_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info("Web server running on port %s", port)
    server.serve_forever()


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN غير موجود في Environment Variables")

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_source))
    app.add_handler(CommandHandler("sources", sources))
    app.add_handler(CommandHandler("remove", remove_source))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    monitor = NewsMonitor(db, channel_id=CHANNEL_ID)
    app.bot_data["monitor"] = monitor

    # فحص دوري كل N من الثواني
    app.job_queue.run_repeating(
        monitor_job,
        interval=CHECK_INTERVAL,
        first=10,
        name="source-monitor",
    )

    # تقرير يومي الساعة 00:00 بتوقيت اليمن
    app.job_queue.run_daily(
        daily_report_job,
        time=time(REPORT_HOUR, REPORT_MINUTE, tzinfo=TIMEZONE),
        name="daily-report",
    )

    logger.info("Mashhad Monitor is starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
