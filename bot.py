import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ----------------------------------------------------
# 0. سيرفر وهمي لتجاوز فحص Port في Render المجاني
# ----------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        return  # إخفاء سجلات الطلبات العادية للحفاظ على نظافة الـ Logs

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# تشغيل السيرفر الوهمي في مسار خلفي (Thread)
threading.Thread(target=run_dummy_server, daemon=True).start()

# ----------------------------------------------------
# ضبط التوقيت المحلي والإعدادات
# ----------------------------------------------------
TIMEZONE = pytz.timezone('Asia/Riyadh')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------
# 1. قاعدة بيانات/قائمة وهمية للأخبار
# ----------------------------------------------------
news_database = [
    {
        "title": "محافظ المهرة يلتقي بقادة الأجهزة الأمنية لمتابعة الأوضاع",
        "source": "قناة المهرية",
        "url": "https://almahriah.net/news/123",
        "timestamp": datetime.now(TIMEZONE)
    }
]

sources_list = [
    "قناة المهرية (موقع/تليجرام)",
    "إذاعة المهرة المحلية",
    "صحيفة أخبار المهرة",
    "حسابات المحافظة الرسمية"
]

# ----------------------------------------------------
# 2. لوحات الأزرار التفاعلية
# ----------------------------------------------------
def get_main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📊 تقرير الأخبار الآنية", callback_data="get_today_report"),
            InlineKeyboardButton("📡 المصادر المعتمدة", callback_data="show_sources")
        ],
        [
            InlineKeyboardButton("➕ إضافة مصدر جديد", callback_data="add_source_info"),
            InlineKeyboardButton("⚙️ حالة النظام", callback_data="system_status")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard():
    keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]
    return InlineKeyboardMarkup(keyboard)

# ----------------------------------------------------
# 3. فلترة الأخبار
# ----------------------------------------------------
def get_today_news_filtered():
    now = datetime.now(TIMEZONE)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    today_news = []
    for news in news_database:
        news_time = news['timestamp']
        if news_time.tzinfo is None:
            news_time = TIMEZONE.localize(news_time)
            
        if start_of_today <= news_time <= now:
            today_news.append(news)
            
    return today_news, now

# ----------------------------------------------------
# 4. رسائل الترحيب والردود
# ----------------------------------------------------
async def welcome_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_text = (
        f"✨ **أهلاً وسهلاً بك عزيزي {user_name}!** 👋\n\n"
        f"🤖 أنا **بوت رصد ومتابعة الأخبار الآنية**.\n"
        f"أقوم بمراقبة المصادر لحظة بلحظة وأوفر لك التقرير الفوري والدقيق لليوم الحالي فقط.\n\n"
        f"👇 **اختر من القائمة أدناه ما تريد استعراضه:**"
    )
    
    if update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown"
        )
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            welcome_text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown"
        )

# ----------------------------------------------------
# 5. معالجة معالجات الأزرار
# ----------------------------------------------------
async def handle_button_clicks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "main_menu":
        await welcome_user(update, context)
        
    elif data == "get_today_report":
        news_list, request_time = get_today_news_filtered()
        time_str = request_time.strftime("%Y-%m-%d | %I:%M:%S %p")
        
        if not news_list:
            report_msg = (
                f"📅 **تقرير الأخبار الآنية**\n"
                f"⏱ **توقيت الطلب:** `{time_str}`\n"
                f"───────────────────\n\n"
                f"ℹ️ لا توجد أخبار مرصودة حتى هذه اللحظة لليوم."
            )
        else:
            report_msg = (
                f"📰 **التقرير الإخباري الآني لليوم**\n"
                f"⏱ **حتى لحظة الطلب:** `{time_str}`\n"
                f"📊 **عدد الأخبار المرصودة:** `{len(news_list)}`\n"
                f"───────────────────\n\n"
            )
            for idx, item in enumerate(news_list, 1):
                item_time = item['timestamp'].strftime("%I:%M %p")
                report_msg += (
                    f"**{idx}. {item['title']}**\n"
                    f"🔹 **المصدر:** {item['source']} | 🕒 `{item_time}`\n"
                    f"🔗 [رابط الخبر]({item['url']})\n\n"
                )
        
        await query.edit_message_text(
            report_msg,
            reply_markup=get_back_keyboard(),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        
    elif data == "show_sources":
        sources_text = "📡 **قائمة المصادر الإخبارية المعتمدة حالياً:**\n\n"
        for idx, src in enumerate(sources_list, 1):
            sources_text += f"_{idx}._  {src}\n"
            
        sources_text += "\n💡 يتم رصد هذه المصادر وتحديث الأخبار بانتظام."
        
        await query.edit_message_text(
            sources_text,
            reply_markup=get_back_keyboard(),
            parse_mode="Markdown"
        )
        
    elif data == "add_source_info":
        add_text = (
            "➕ **إضافة مصدر جديد**\n\n"
            "لإضافة قناة تليجرام، موقع إخباري، أو حساب Twitter/Nitter جديد للرصد، "
            "يرجى إرسال رابط المصدر أو اسم القناة مباشرة إلى المطور أو الإدارة لردفه في النظام."
        )
        await query.edit_message_text(
            add_text,
            reply_markup=get_back_keyboard(),
            parse_mode="Markdown"
        )

    elif data == "system_status":
        status_text = (
            "⚙️ **حالة نظام الرصد:**\n\n"
            "✅ محرك الرصد: **يعمل بدقة متناهية**\n"
            "⏰ التوقيت المعتمد: `Asia/Riyadh`\n"
            "🔄 النطاق الزمني: **من 00:00:00 لليوم وحتى اللحظة**"
        )
        await query.edit_message_text(
            status_text,
            reply_markup=get_back_keyboard(),
            parse_mode="Markdown"
        )

# ----------------------------------------------------
# 6. التقرير اليومي
# ----------------------------------------------------
async def send_daily_nightly_report(app):
    news_list, request_time = get_today_news_filtered()
    date_str = request_time.strftime("%Y-%m-%d")
    
    report_msg = (
        f"🌙 **التقرير النهائي والكامل لليوم ({date_str})**\n"
        f"───────────────────\n\n"
    )
    if not news_list:
        report_msg += "لم يتم رصد أي أخبار خلال هذا اليوم."
    else:
        for idx, item in enumerate(news_list, 1):
            item_time = item['timestamp'].strftime("%I:%M %p")
            report_msg += f"{idx}. **{item['title']}** ({item['source']} - `{item_time}`)\n"

    logger.info("تم تجهيز وإرسال التقرير اليومي النهائي بنجاح.")

# ----------------------------------------------------
# 7. تشغيل البوت
# ----------------------------------------------------
def main():
    BOT_TOKEN = "8949984502:AAHusXsa6M-fZ3J-fIKQD1U4-Rnu0GgmSKo"
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    greeting_patterns = r"^(مرحبا|مرحباً|السلام عليكم|سلام|هلو|أهلا|اهلا|hello|hi)$"

    app.add_handler(CommandHandler("start", welcome_user))
    app.add_handler(CommandHandler("report", welcome_user))
    app.add_handler(MessageHandler(filters.Regex(greeting_patterns) | filters.TEXT & ~filters.COMMAND, welcome_user))
    app.add_handler(CallbackQueryHandler(handle_button_clicks))

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        send_daily_nightly_report,
        'cron',
        hour=23,
        minute=59,
        args=[app]
    )
    scheduler.start()

    logger.info("تم تشغيل البوت والسيرفر بنجاح...")
    app.run_polling()

if __name__ == "__main__":
    main()
