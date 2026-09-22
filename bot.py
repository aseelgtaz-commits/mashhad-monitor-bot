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
# 0. سيرفر وهمي لتجاوز فحص Port في Render
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
# الإعدادات وقواعد البيانات
# ----------------------------------------------------
TIMEZONE = pytz.timezone("Asia/Riyadh")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# محاولة الاتصال بقاعدة البيانات مع حماية
try:
  db = Database()
  monitor = NewsMonitor(db)
except Exception as e:
  logger.error(f"DB Initialization Error: {e}")
  db = None
  monitor = None

# ----------------------------------------------------
# الأزرار واللوحات
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
      "🏛 <b>مرحباً بك أستاذ أصيل!</b> 🎙\n\n"
      "أنا <b>مساعدك الذكي المخصص لرصد ومتابعة مستجدات محافظة المهرة</b>"
      " لحظة بلحظة.\n"
      "أقوم بتتبع المنصات الإخبارية والمصادر المعتمدة فور صدورها، وأضع بين"
      " يديك تقريراً شاملاً ومنظماً للحدث.\n\n"
      "📌 <b>يرجى اختيار الخيار المطلوب من لوحة التحكم أدناه:</b>"
  )

  if update.message:
    await update.message.reply_text(
        welcome_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML"
    )
  elif update.callback_query:
    try:
      await update.callback_query.edit_message_text(
          welcome_text,
          reply_markup=get_main_menu_keyboard(),
          parse_mode="HTML",
      )
    except Exception:
      pass


async def handle_button_clicks(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  query = update.callback_query
  if not query:
    return

  # الإجابة الفورية المباشرة للتليجرام لإيقاف مؤشر الانتظار فوراً
  try:
    await query.answer()
  except Exception as e:
    logger.warning(f"Answer error: {e}")

  data = query.data
  logger.info(f"Button pressed: {data}")

  # 1. العودة للقائمة الرئيسية
  if data == "main_menu":
    await welcome_user(update, context)
    return

  # 2. اقتراح مصدر (لا يستدعي قاعدة البيانات - لا يسبب تعليق)
  if data == "add_source_info":
    add_text = (
        "➕ <b>طلب إضافة مصدر جديد للشبكة</b>\n\n"
        "لإدراج صحيفة، موقع، أو منصة إخبارية جديدة ضمن خطة الرصد التلقائي،"
        " يرجى إرسال رابط المصدر المباشر للإدارة."
    )
    await query.edit_message_text(
        add_text, reply_markup=get_back_keyboard(), parse_mode="HTML"
    )
    return

  # 3. الفحوصات التي تعتمد على قاعدة البيانات
  if not db:
    await query.edit_message_text(
        "⚠️ قاعدة البيانات غير متصلة حالياً، يرجى التحقق من إعدادات الاتصال.",
        reply_markup=get_back_keyboard(),
    )
    return

  try:
    if data == "get_today_report":
      now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d | %I:%M:%S %p")
      try:
        items = db.get_today_items()
      except Exception as db_err:
        logger.error(f"DB error: {db_err}")
        items = []

      if not items:
        report_msg = (
            f"📑 <b>موجز الأخبار الآنية</b>\n"
            f"⏱ <b>توقيت الاستعلام:</b> <code>{now_str}</code>\n"
            f"───────────────────\n\n"
            f"ℹ️ لم يتم تسجيل أي مستجدات إخبارية جديدة حتى هذه اللحظة."
        )
      else:
        report_msg = (
            f"📰 <b>الموجز الإخباري الخاص لليوم</b>\n"
            f"⏱ <b>تحديث:</b> <code>{now_str}</code>\n"
            f"📊 <b>إجمالي الأحداث المرصودة:</b> <code>{len(items)}</code>"
            " خبر\n"
            f"───────────────────\n\n"
        )
        for idx, item in enumerate(items, 1):
          title = item.get("title", "بدون عنوان")
          src_name = item.get("source_name", "مصدر غير معروف")
          link = item.get("link", "#")
          report_msg += (
              f"<b>{idx}. {title}</b>\n"
              f"🔹 <b>المصدر:</b> {src_name}\n"
              f'🔗 <a href="{link}">المادة الكاملة</a>\n\n'
          )

      await query.edit_message_text(
          report_msg,
          reply_markup=get_back_keyboard(),
          parse_mode="HTML",
          disable_web_page_preview=True,
      )

    elif data == "show_sources":
      try:
        sources = db.list_sources()
      except Exception as db_err:
        logger.error(f"DB error: {db_err}")
        sources = []

      sources_text = (
          "📡 <b>قائمة شبكة المصادر والمنصات المعتمدة للرصد:</b>\n\n"
      )
      if not sources:
        sources_text += "لا توجد مصادر مضافة حالياً في قاعدة البيانات."
      else:
        for idx, src in enumerate(sources, 1):
          status = "🟢 نشط" if src.get("enabled", True) else "🔴 متوقف"
          name = src.get("name", "مصدر")
          sources_text += f"<b>{idx}. {name}</b> | {status}\n"

      await query.edit_message_text(
          sources_text, reply_markup=get_back_keyboard(), parse_mode="HTML"
      )

    elif data == "system_status":
      try:
        stats = db.dashboard_stats()
        sources_cnt = stats.get("sources", 0)
        enabled_cnt = stats.get("enabled_sources", 0)
        today_cnt = stats.get("items_today", 0)
      except Exception as db_err:
        logger.error(f"DB error: {db_err}")
        sources_cnt, enabled_cnt, today_cnt = 0, 0, 0

      status_text = (
          f"⚙️ <b>تقرير المؤشرات التشغيلية للنظام:</b>\n\n"
          f"📡 إجمالي المنصات المسجلة: <code>{sources_cnt}</code>\n"
          f"🟢 المصادر الفعالة حالياً: <code>{enabled_cnt}</code>\n"
          f"📰 الأخبار المرصودة اليوم: <code>{today_cnt}</code>\n"
          f"⏰ النطاق الزمني: <code>Asia/Riyadh</code>"
      )
      await query.edit_message_text(
          status_text, reply_markup=get_back_keyboard(), parse_mode="HTML"
      )

  except Exception as e:
    logger.error(f"General callback handler error: {e}")

    try:
      await query.edit_message_text(
          "⚠️ تعذر استكمال الطلب حالياً، يرجى إعادة المحاولة.",
          reply_markup=get_back_keyboard(),
      )
    except Exception:
      pass


async def run_periodic_monitoring():
  if monitor:
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
  app.add_handler(CallbackQueryHandler(handle_button_clicks))
  app.add_handler(
      MessageHandler(
          filters.Regex(greeting_patterns)
          | filters.TEXT & ~filters.COMMAND,
          welcome_user,
      )
  )

  if monitor:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(run_periodic_monitoring, "interval", minutes=5)
    scheduler.start()

  logger.info("تم تشغيل البوت بنجاح...")
  app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
  main()
