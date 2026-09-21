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
from monitor import Monitor


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
        await update.effective_message.reply_text(
            "⛔ هذا الأمر متاح للمشرفين فقط."
        )


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
            InlineKeyboardButton("🔴 مشاكل المصادر", callback_data="errors"),
        ],
    ]

    text = (
        "🛰 *مرحباً بك في Mashhad Monitor*\n\n"
        "نظام رصد ومتابعة للمصادر والأخبار والمستجدات.\n\n"
        f"📡 المصادر: {stats['sources']}\n"
        f"🟢 النشطة: {stats['enabled_sources']}\n"
        f"📰 مواد اليوم: {stats['items_today']}\n"
        f"📢 منشور اليوم: {stats['published_today']}\n\n"
        "من هنا يمكنك إدارة المصادر ومتابعة الرصد."
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    await update.message.reply_text(
        "📚 *مساعدة Mashhad Monitor*\n\n"
        "➕ إضافة مصدر:\n"
        "`/add اسم المصدر | الرابط`\n\n"
        "📡 عرض المصادر:\n"
        "`/sources`\n\n"
        "🗑 حذف مصدر:\n"
        "`/remove رقم_المصدر`\n\n"
        "📊 التقرير:\n"
        "`/report`\n\n"
        "سيتم لاحقاً توسيع لوحة التحكم والأزرار.",
        parse_mode="Markdown",
    )


async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    text = update.message.text.partition(" ")[2].strip()

    if "|" not in text:
        await update.message.reply_text(
            "➕ أرسل المصدر بهذا الشكل:\n\n"
            "`/add اسم المصدر | https://example.com`",
            parse_mode="Markdown",
        )
        return

    name, url = [x.strip() for x in text.split("|", 1)]

    if not name or not url.startswith(("http://", "https://")):
        await update.message.reply_text("❌ اسم المصدر أو الرابط غير صالح.")
        return

    try:
        source_id = db.add_source(name, url)
    except ValueError as exc:
        await update.message.reply_text(f"⚠️ {exc}")
        return
    except Exception:
        logger.exception("Failed to add source")
        await update.message.reply_text("❌ حدث خطأ أثناء حفظ المصدر.")
        return

    await update.message.reply_text(
        "✅ *تمت إضافة المصدر*\n\n"
        f"📡 {name}\n"
        f"🔗 {url}\n"
        f"🆔 {source_id}\n\n"
        "سيتم إدخاله في دورة الرصد القادمة.",
        parse_mode="Markdown",
    )


async def sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    rows = db.list_sources()

    if not rows:
        await update.message.reply_text("📡 لا توجد مصادر مضافة حالياً.")
        return

    lines = ["📡 *المصادر المضافة*", ""]
    for index, row in enumerate(rows, 1):
        status = "🟢 نشط" if row["enabled"] else "⏸ متوقف"
        error = f"\n   ⚠️ {row['last_error']}" if row["last_error"] else ""
        lines.append(
            f"{index}. *{row['name']}*\n"
            f"   {status}\n"
            f"   🔗 {row['url']}{error}"
        )

    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    text = update.message.text.partition(" ")[2].strip()

    try:
        number = int(text)
    except ValueError:
        await update.message.reply_text("استخدم: `/remove 1`", parse_mode="Markdown")
        return

    rows = db.list_sources()

    if number < 1 or number > len(rows):
        await update.message.reply_text("❌ رقم المصدر غير صحيح.")
        return

    row = rows[number - 1]
    db.remove_source(row["id"])

    await update.message.reply_text(
        f"🗑 تم حذف المصدر: *{row['name']}*",
        parse_mode="Markdown",
    )


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await denied(update)
        return

    report = db.build_daily_report()
    await update.message.reply_text(report, parse_mode="Markdown")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        await query.edit_message_text("⛔ غير مصرح.")
        return

    if query.data == "add_help":
        await query.edit_message_text(
            "➕ أرسل:\n\n`/add اسم المصدر | https://example.com`",
            parse_mode="Markdown",
        )
    elif query.data == "sources":
        await sources(update, context)
    elif query.data == "report":
        await report_command(update, context)
    elif query.data == "errors":
        rows = db.sources_with_errors()
        if not rows:
            await query.edit_message_text("🟢 لا توجد مصادر بها أخطاء مسجلة.")
            return
        text = "🔴 *مصادر بها أخطاء*\n\n" + "\n\n".join(
            f"• *{r['name']}*\n{r['last_error']}" for r in rows
        )
        await query.edit_message_text(text, parse_mode="Markdown")


async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    monitor = context.application.bot_data["monitor"]
    try:
        await monitor.run_once(context.application.bot)
    except Exception:
        logger.exception("Monitor cycle failed")


async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    report = db.build_daily_report()

    # The report is intentionally sent to the configured channel.
    if CHANNEL_ID:
        try:
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=report,
                parse_mode="Markdown",
            )
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

    monitor = Monitor(db)
    app.bot_data["monitor"] = monitor

    # Monitor every N seconds.
    app.job_queue.run_repeating(
        monitor_job,
        interval=CHECK_INTERVAL,
        first=10,
        name="source-monitor",
    )

    # Daily report at 00:00 Asia/Aden.
    app.job_queue.run_daily(
        daily_report_job,
        time=time(REPORT_HOUR, REPORT_MINUTE, tzinfo=TIMEZONE),
        name="daily-report",
    )

    logger.info("Mashhad Monitor is starting...")
    logger.info("Timezone: %s", TIMEZONE)
    logger.info("Check interval: %s seconds", CHECK_INTERVAL)
    logger.info("Daily report: %02d:%02d", REPORT_HOUR, REPORT_MINUTE)

    # One Render service / one polling process must use this bot token.
    asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

