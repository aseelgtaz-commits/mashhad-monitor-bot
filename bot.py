import logging
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import Database
from monitor import NewsMonitor

# ----------------------------------------------------
# 0. سيرفر وهمي لتجاوز فحص Port في Render المجاني
# ----------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):

  def do_GET(self):
    self.send_response(200)
    self.end_headers()
    self.wfile.write(b"Bot is alive!")

  def log_message(self, format, *args):
    return


def run_dummy_server():
  port = int(os.environ.get("PORT", 10000))
  server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
  server.serve_forever()


threading.Thread(target=run_dummy_server, daemon=True).start()

# ----------------------------------------------------
# ضبط التوقيت والإعدادات وقواعد البيانات
# ----------------------------------------------------
TIMEZONE = pytz.timezone("Asia/Riyadh")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

db = Database()
monitor = NewsMonitor(db)

# ----------------------------------------------------
# اللوحات والأزرار المحدثة
# ----------------------------------------------------


def get_main_menu_keyboard():
  keyboard = [
      [
          InlineKeyboardButton(
              "📰 موجز الأخبار الآنية", callback_data="get_today_report"
          ),
          InlineKeyboardButton(
              "📡 شبكة المصادر المعتمدة", callback_data="show_sources"
          ),
      ],
      [
          InlineKeyboardButton(
              "➕ اقتراح مصدر جديد", callback_data="add_source_info"
          ),
          InlineKeyboardButton(
              "⚙️ مؤشرات أداء النظام", callback_data="system_status"
          ),
      ],
  ]
  return InlineKeyboardMarkup(keyboard)


def get_back_keyboard():
  keyboard = [[
      InlineKeyboardButton(
          "🔙 العودة إلى لوحة التحكم الرئيسية", callback_data="main_menu"
      )
  ]]
  return InlineKeyboardMarkup(keyboard)


# ----------------------------------------------------
# التفاعل والأوامر
# ----------------------------------------------------


async def welcome_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
  welcome_text = (
      "🏛 **مرحباً بك أستاذ أصيل!** 🎙\n\n"
      "أنا **مساعدك الذكي المخصص لرصد ومتابعة مستجدات محافظة المهرة** "
      "لحظة بلحظة.\n"
      "أقوم بتتبع المنصات الإخبارية والمصادر المعتمدة فور صدورها، وأضع بين"
      " يديك تقريراً شاملاً ومنظماً للحدث.\n\n"
      "📌 **يرجى اختيار الخيار المطلوب من لوحة التحكم أدناه:**"
  )

  if update.message:
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown",
    )
  elif update.callback_query:
    try:
      await update.callback_query.edit_message_text(
          welcome_text,
          reply_markup=get_main_menu_keyboard(),
          parse_mode="Markdown",
      )
    except Exception as e:
      logger.warning(f"Error editing message: {e}")
      await update.callback_query.message.reply_text(
          welcome_text,
          reply_markup=get_main_menu_keyboard(),
          parse_mode="Markdown",
      )


async def handle_button_clicks(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  query = update.callback_query
  if not query:
    return

  try:
    await query.answer()
  except Exception as e:
    logger.warning(f"Answer query failed: {e}")

  data = query.data
  logger.info(f"Button pressed: {data}")

  try:
    if data == "main_menu":
      await welcome_user(update, context)

    elif data == "get_today_report":
      try:
        items = db.get_today_items()
      except Exception as e:
        logger.error(f"Error fetching DB items: {e}")
        items = []

      now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d | %I:%M:%S %p")

      if not items:
        report_msg = (
            f"📑 **موجز الأخبار الآنية**\n"
            f"⏱ **توقيت الاستعلام:** `{now_str}`\n"
            f"───────────────────\n\n"
            f"ℹ️ لم يتم تسجيل أي مستجدات إخبارية جديدة حتى هذه اللحظة."
        )
      else:
        report_msg = (
            f"📰 **الموجز الإخباري الخاص لليوم**\n"
            f"⏱ **تحديث:** `{now_str}`\n"
            f"📊 **إجمالي الأحداث المرصودة:** `{len(items)}` خبر\n"
            f"───────────────────\n\n"
        )
        for idx, item in enumerate(items, 1):
          title = item.get("title", "بدون عنوان")
          src_name = item.get("source_name", "مصدر غير معروف")
          link = item.get("link", "#")
          report_msg += (
              f"**{idx}. {title}**\n"
              f"🔹 **المصدر:** {src_name}\n"
              f"🔗 [المادة الكاملة]({link})\n\n"
          )

      await query.edit_message_text(
          report_msg,
          reply_markup=get_back_keyboard(),
          parse_mode="Markdown",
          disable_web_page_preview=True,
      )

    elif data == "show_sources":
      try:
        sources = db.list_sources()
      except Exception as e:
        logger.error(f"Error fetching sources: {e}")
        sources = []

      sources_text = (
          "📡 **قائمة شبكة المصادر والمنصات المعتمدة للرصد:**\n\n"
      )
      if not sources:
        sources_text += "لا توجد مصادر مضافة حالياً في قاعدة البيانات."
      else:
        for idx, src in enumerate(sources, 1):
          status = "🟢 نشط" if src.get("enabled", True) else "🔴 متوقف"
          name = src.get("name", "مصدر")
          sources_text += f"**{idx}. {name}** | {status}\n"

      await query.edit_message_text(
          sources_text, reply_markup=get_back_keyboard(), parse_mode="Markdown"
      )

    elif data == "add_source_info":
      add_text = (
          "➕ **طلب إضافة مصدر جديد للشبكة**\n\n"
          "لإدراج صحيفة، موقع، أو منصة إخبارية جديدة ضمن خطة الرصد"
          " التلقائي، يرجى إرسال رابط المصدر المباشر للإدارة."
      )
      await query.edit_message_text(
          add_text, reply_markup=get_back_keyboard(), parse_mode="Markdown"
      )

    elif data == "system_status":
      try:
        stats = db.dashboard_stats()
        sources_cnt = stats.get("sources", 0)
        enabled_cnt = stats.get("enabled_sources", 0)
        today_cnt = stats.get("items_today", 0)
      except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        sources_cnt, enabled_cnt, today_cnt = 0, 0, 0

      status_text = (
          f"⚙️ **تقرير المؤشرات التشغيلية للنظام:**\n\n"
          f"📡 إجمالي المنصات المسجلة: `{sources_cnt}`\n"
          f"🟢 المصادر الفعالة حالياً: `{enabled_cnt}`\n"
          f"📰 الأخبار المرصودة اليوم: `{today_cnt}`\n"
          f"⏰ النطاق الزمني: `Asia/Riyadh`"
      )
      await query.edit_message_text(
          status_text, reply_markup=get_back_keyboard(), parse_mode="Markdown"
      )

    else:
      await welcome_user(update, context)

  except Exception as e:
    logger.error(f"Error handling button click '{data}': {e}")
    await query.edit_message_text(
        "⚠️ حدث خطأ أثناء تنفيذ الطلب، يرجى إعادة محاولة الضغط.",
        reply_markup=get_back_keyboard(),
    )


async def run_periodic_monitoring():
  try:
    await monitor.run_once()
  except Exception as e:
    logger.error(f"خطأ أثناء دورة الرصد: {e}")


# ----------------------------------------------------
# التشغيل
# ----------------------------------------------------
def main():
  BOT_TOKEN = os.environ.get(
      "BOT_TOKEN", "8949984502:AAHusXsa6M-fZ3J-fIKQD1U4-Rnu0GgmSKo"
  )
  app = ApplicationBuilder().token(BOT_TOKEN).build()

  greeting_patterns = r"^(مرحبا|مرحباً|السلام عليكم|سلام|هلو|أهلا|اهلا|hello|hi)$"

  app.add_handler(CommandHandler("start", welcome_user))
  app.add_handler(CommandHandler("report", welcome_user))
  app.add_handler(
      MessageHandler(
          filters.Regex(greeting_patterns)
          | filters.TEXT & ~filters.COMMAND,
          welcome_user,
      )
  )
  app.add_handler(CallbackQueryHandler(handle_button_clicks))

  scheduler = AsyncIOScheduler(timezone=TIMEZONE)
  scheduler.add_job(run_periodic_monitoring, "interval", minutes=5)
  scheduler.start()

  logger.info("تم تشغيل البوت المطور بنجاح...")
  app.run_polling()


if __name__ == "__main__":
  main()
