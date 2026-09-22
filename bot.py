from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging
import os
import threading
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
    self.wfile.write(b'Bot is alive!')

  def log_message(self, format, *args):
    return


def run_dummy_server():
  port = int(os.environ.get('PORT', 10000))
  server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
  server.serve_forever()


threading.Thread(target=run_dummy_server, daemon=True).start()

# ----------------------------------------------------
# ضبط التوقيت والإعدادات وقواعد البيانات
# ----------------------------------------------------
TIMEZONE = pytz.timezone('Asia/Riyadh')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

db = Database()
monitor = NewsMonitor(db)

# ----------------------------------------------------
# اللوحات والأزرار
# ----------------------------------------------------


def get_main_menu_keyboard():
  keyboard = [
      [
          InlineKeyboardButton(
              '📊 تقرير الأخبار الآنية', callback_data='get_today_report'
          ),
          InlineKeyboardButton(
              '📡 المصادر المعتمدة', callback_data='show_sources'
          ),
      ],
      [
          InlineKeyboardButton(
              '➕ إضافة مصدر جديد', callback_data='add_source_info'
          ),
          InlineKeyboardButton('⚙️ حالة النظام', callback_data='system_status'),
      ],
  ]
  return InlineKeyboardMarkup(keyboard)


def get_back_keyboard():
  keyboard = [[
      InlineKeyboardButton(
          '🔙 العودة للقائمة الرئيسية', callback_data='main_menu'
      )
  ]]
  return InlineKeyboardMarkup(keyboard)


# ----------------------------------------------------
# التفاعل والأوامر
# ----------------------------------------------------


async def welcome_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_name = update.effective_user.first_name
  welcome_text = (
      f'✨ **أهلاً وسهلاً بك عزيزي {user_name}!** 👋\n\n'
      f'🤖 أنا **بوت رصد ومتابعة أخبار المهرة الآنية**.\n'
      f'أقوم بمراقبة المصادر لحظة بلحظة وأوفر لك التقرير الفوري لليوم'
      ' الحالي.\n\n'
      f'👇 **اختر من القائمة أدناه ما تريد استعراضه:**'
  )

  if update.message:
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown',
    )
  elif update.callback_query:
    try:
      await update.callback_query.edit_message_text(
          welcome_text,
          reply_markup=get_main_menu_keyboard(),
          parse_mode='Markdown',
      )
    except Exception:
      # في حال كانت الرسالة قديمة جداً ولا يمكن تعديلها، يرسل رسالة جديدة
      await update.callback_query.message.reply_text(
          welcome_text,
          reply_markup=get_main_menu_keyboard(),
          parse_mode='Markdown',
      )


async def handle_button_clicks(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  query = update.callback_query
  await query.answer()
  data = query.data

  if data == 'main_menu':
    await welcome_user(update, context)

  elif data == 'get_today_report':
    items = db.get_today_items()
    now_str = datetime.now(TIMEZONE).strftime('%Y-%m-%d | %I:%M:%S %p')

    if not items:
      report_msg = (
          f'📅 **تقرير الأخبار الآنية**\n'
          f'⏱ **توقيت الطلب:** `{now_str}`\n'
          f'───────────────────\n\n'
          f'ℹ️ لا توجد أخبار مرصودة حتى هذه اللحظة لليوم.'
      )
    else:
      report_msg = (
          f'📰 **التقرير الإخباري الآني لليوم**\n'
          f'⏱ **حتى لحظة الطلب:** `{now_str}`\n'
          f'📊 **عدد الأخبار المرصودة:** `{len(items)}`\n'
          f'───────────────────\n\n'
      )
      for idx, item in enumerate(items, 1):
        report_msg += (
            f'**{idx}. {item["title"]}**\n'
            f'🔹 **المصدر:** {item["source_name"]}\n'
            f'🔗 [رابط الخبر]({item["link"]})\n\n'
        )

    await query.edit_message_text(
        report_msg,
        reply_markup=get_back_keyboard(),
        parse_mode='Markdown',
        disable_web_page_preview=True,
    )

  elif data == 'show_sources':
    sources = db.list_sources()
    sources_text = '📡 **قائمة المصادر الإخبارية المعتمدة حالياً:**\n\n'
    for idx, src in enumerate(sources, 1):
      status = '✅' if src.get('enabled', True) else '❌'
      sources_text += f'{idx}. {src["name"]} {status}\n'

    await query.edit_message_text(
        sources_text, reply_markup=get_back_keyboard(), parse_mode='Markdown'
    )

  elif data == 'add_source_info':
    add_text = (
        '➕ **إضافة مصدر جديد**\n\n'
        'لإضافة موقع أو قناة جديدة للرصد، يرجى تزويد الإدارة برابط المصدر'
        ' المباشر.'
    )
    await query.edit_message_text(
        add_text, reply_markup=get_back_keyboard(), parse_mode='Markdown'
    )

  elif data == 'system_status':
    stats = db.dashboard_stats()
    status_text = (
        f'⚙️ **حالة نظام الرصد:**\n\n'
        f'📡 المصادر الإجمالية: `{stats["sources"]}`\n'
        f'✅ المصادر النشطة: `{stats["enabled_sources"]}`\n'
        f'📰 أخبار اليوم المرصودة: `{stats["items_today"]}`\n'
        f'⏰ التوقيت المعتمد: `Asia/Riyadh`'
    )
    await query.edit_message_text(
        status_text, reply_markup=get_back_keyboard(), parse_mode='Markdown'
    )

  else:
    # أي زر قديم أو غير معروف يعيد توجيه المستخدم للقائمة الرئيسية تلقائياً
    await welcome_user(update, context)


async def send_daily_nightly_report(app):
  report_text = db.build_daily_report()
  logger.info('تم إعداد التقرير اليومي بنجاح.')


async def run_periodic_monitoring():
  """مهمة دورية تفحص الأخبار والمواقع كل 5 دقائق"""
  try:
    await monitor.run_once()
  except Exception as e:
    logger.error(f'خطأ أثناء دورة الرصد: {e}')


# ----------------------------------------------------
# التشغيل
# ----------------------------------------------------
def main():
  BOT_TOKEN = os.environ.get(
      'BOT_TOKEN', '8949984502:AAHusXsa6M-fZ3J-fIKQD1U4-Rnu0GgmSKo'
  )
  app = ApplicationBuilder().token(BOT_TOKEN).build()

  greeting_patterns = r'^(مرحبا|مرحباً|السلام عليكم|سلام|هلو|أهلا|اهلا|hello|hi)$'

  app.add_handler(CommandHandler('start', welcome_user))
  app.add_handler(CommandHandler('report', welcome_user))
  app.add_handler(
      MessageHandler(
          filters.Regex(greeting_patterns)
          | filters.TEXT & ~filters.COMMAND,
          welcome_user,
      )
  )
  app.add_handler(CallbackQueryHandler(handle_button_clicks))

  scheduler = AsyncIOScheduler(timezone=TIMEZONE)

  # تشغيل عملية الرصد التلقائية كل 5 دقائق
  scheduler.add_job(run_periodic_monitoring, 'interval', minutes=5)

  # إرسال التقرير النهائي الساعة 23:59
  scheduler.add_job(
      send_daily_nightly_report, 'cron', hour=23, minute=59, args=[app]
  )

  scheduler.start()

  logger.info('تم تشغيل البوت والمحرك بنجاح...')
  app.run_polling()


if __name__ == '__main__':
  main()
