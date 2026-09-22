# Mashhad Monitor Bot — V3 Word

نسخة V3 مخصصة للرصد وإنتاج تقارير Word قابلة للتحرير.

## الوظائف
- رصد المصادر الموجودة في `sources.json` مع عزل أخطاء كل مصدر.
- تخزين دائم في SQLite ومنع تكرار المادة بواسطة الرابط.
- فلترة أولية للمواد ذات الصلة بالمهرة.
- واجهة Telegram للتحكم.
- زر **📰 إنشاء موجز Word** لإنتاج ملف `.docx` وإرساله مباشرة.
- تقرير يومي تلقائي الساعة `00:00` وفق `TIMEZONE` (الافتراضي `Asia/Aden`).
- تقرير Word منظم وقابل للتحرير، مع روابط قابلة للنقر.
- خادم Health مناسب لـ Render.

## التشغيل على Render
Start Command:
```text
python bot.py
```

يفضل استخدام Python 3.12 كما هو محدد في `python-version.txt`.

## متغيرات البيئة
راجع `.env.example`، وأدخل `BOT_TOKEN` و`CHANNEL_ID` في Render Environment Variables.

## ملاحظة
لا ترفع `__pycache__` أو ملفات `.pyc` إلى المشروع. Python ينشئها تلقائيًا عند الحاجة.

يجب تشغيل نسخة واحدة فقط من البوت باستخدام نفس `BOT_TOKEN` عند استعمال polling.

