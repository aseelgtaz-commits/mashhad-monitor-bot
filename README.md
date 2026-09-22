# Mashhad Monitor Bot — V2

نسخة محسنة من البوت الحالي مع التركيز على استقرار Telegram callbacks، عزل أخطاء المصادر، وعدم ابتلاع الاستثناءات.

## أهم التحسينات

- `CallbackQueryHandler` يعمل مباشرة مع `query.answer()` قبل أي عملية طويلة.
- تسجيل واضح لوصول الـ callback والرد عليه وفشل التنفيذ.
- إضافة `Application` error handler.
- إزالة إنشاء Event Loop يدوي.
- `run_polling()` هو نقطة تشغيل Telegram الوحيدة.
- عمليات SQLite داخل handlers تُنفذ عبر `asyncio.to_thread` حتى لا تحجز Event Loop.
- Scheduler واحد مع منع تداخل دورات الرصد.
- توقيت موحد من `TIMEZONE`، والافتراضي `Asia/Aden`.
- تقرير يومي الساعة 00:00 حسب `TIMEZONE`.
- عزل أخطاء كل مصدر عن بقية المصادر.
- تسجيل حالة آخر فحص للمصدر وعدد الأخطاء المتتالية.
- استخدام `mahra_filter.py` فعلياً.
- منع تكرار المواد بواسطة الرابط UNIQUE.
- حماية أفضل للنصوص والروابط عند إرسال HTML إلى Telegram.
- Health server منفصل بخيط مستقل لخدمة Render.

## Render

Start Command:

```text
python bot.py
```

يجب تشغيل نسخة واحدة فقط من البوت عند استخدام polling بنفس `BOT_TOKEN`.

## التحديث

استبدل الملفات القديمة بالملفات الجديدة:

- `bot.py`
- `monitor.py`
- `database.py`
- `mahra_filter.py`
- `requirements.txt`
- `.env.example`
- `README.md`

اترك `sources.json` كما هو في هذه المرحلة.

## ملاحظة قاعدة البيانات

النسخة الجديدة تضيف أعمدة وجداول/فهارس بشكل متوافق باستخدام `CREATE TABLE IF NOT EXISTS` وعمليات إضافة آمنة، لكنها لا تحذف قاعدة البيانات القديمة تلقائياً.

