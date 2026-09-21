import os
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


DATA_FILE = "sources.json"


def load_sources():
    if not os.path.exists(DATA_FILE):
        return []

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_sources(sources):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "مرحباً بك في مرصد المشهد الشرقي 🛰\n\n"
        "أنا بوت لرصد المصادر والأخبار.\n\n"
        "الأوامر المتاحة:\n"
        "/add - إضافة مصدر\n"
        "/sources - عرض المصادر\n"
        "/remove - حذف مصدر\n"
        "/help - المساعدة"
    )
    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "لإضافة مصدر استخدم:\n"
        "/add اسم المصدر | الرابط\n\n"
        "مثال:\n"
        "/add قناة إخبارية | https://example.com"
    )


async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("/add", "", 1).strip()

    if "|" not in text:
        await update.message.reply_text(
            "استخدم الصيغة التالية:\n"
            "/add اسم المصدر | الرابط"
        )
        return

    name, url = [x.strip() for x in text.split("|", 1)]

    sources = load_sources()

    sources.append({
        "name": name,
        "url": url
    })

    save_sources(sources)

    await update.message.reply_text(
        f"تمت إضافة المصدر بنجاح ✅\n\n"
        f"المصدر: {name}\n"
        f"الرابط: {url}"
    )


async def sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = load_sources()

    if not items:
        await update.message.reply_text("لا توجد مصادر مضافة حالياً.")
        return

    text = "📡 المصادر المضافة:\n\n"

    for i, source in enumerate(items, 1):
        text += f"{i}. {source['name']}\n{source['url']}\n\n"

    await update.message.reply_text(text)


async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("/remove", "", 1).strip()

    try:
        number = int(text)
    except:
        await update.message.reply_text(
            "اكتب رقم المصدر الذي تريد حذفه.\n"
            "مثال: /remove 1"
        )
        return

    sources = load_sources()

    if number < 1 or number > len(sources):
        await update.message.reply_text("رقم المصدر غير صحيح.")
        return

    removed = sources.pop(number - 1)

    save_sources(sources)

    await update.message.reply_text(
        f"تم حذف المصدر: {removed['name']} ✅"
    )


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        return


def run_web_server():
    port = int(os.environ.get("PORT", 10000))

    server = HTTPServer(("0.0.0.0", port), HealthHandler)

    print(f"Web server running on port {port}")

    server.serve_forever()


def main():
    token = os.getenv("BOT_TOKEN")

    if not token:
        raise RuntimeError("BOT_TOKEN غير موجود")

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_source))
    app.add_handler(CommandHandler("sources", sources))
    app.add_handler(CommandHandler("remove", remove_source))

    print("Bot is running...")

    app.run_polling()


if __name__== "__main__":
    main()
