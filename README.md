# 🏠 WBS Housing Bot — Berlin

بوت تيليجرام يراقب **شقق WBS 100 في برلين** من أكثر من 10 مصادر حكومية وخاصة، ويرسل إشعاراً فورياً لكل شقة جديدة تطابق معاييرك.

---

## ✨ المزايا

| الميزة | التفاصيل |
|--------|----------|
| 🔍 10 مصادر | Gewobag، Degewo، Howoge، Stadt und Land، Deutsche Wohnen، Berlinovo، ImmobilienScout24، Immowelt، WG-Gesucht، Kleinanzeigen |
| ⚡ سرعة | كل المصادر تُجمَع بالتوازي كل 2-3 دقائق |
| 🎯 تصفية ذكية | WBS + سعر + عدد غرف + حي |
| 🔁 بدون تكرار | قاعدة بيانات SQLite تتذكر كل الشقق المرسلة |
| 🌐 استقرار | Retry تلقائي، تدوير User-Agent، دعم Proxy |
| 🌙 24/7 | يعمل على Railway أو Render بشكل مستمر |

---

## 📁 هيكل المشروع

```
wbs-housing-bot/
├── main.py                  # نقطة الدخول الرئيسية
├── requirements.txt
├── .env.example
├── Procfile                 # Railway/Render
├── railway.toml
├── render.yaml
│
├── config/
│   └── settings.py          # كل الإعدادات من .env
│
├── database/
│   └── db.py                # SQLite async
│
├── filters/
│   └── wbs_filter.py        # فلاتر WBS + سعر + غرف + منطقة + تقييم
│
├── scrapers/
│   ├── base_scraper.py      # HTTP client مشترك مع retry
│   ├── gewobag.py
│   ├── degewo.py
│   ├── howoge.py
│   ├── stadtundland.py
│   ├── deutschewohnen.py
│   ├── berlinovo.py
│   ├── immoscout.py
│   ├── wggesucht.py
│   ├── ebay_kleinanzeigen.py
│   └── immowelt.py
│
├── scheduler/
│   └── runner.py            # حلقة الكشط والإشعارات
│
├── bot/
│   └── handlers.py          # أوامر تيليجرام + تنسيق الرسائل
│
└── utils/
    └── logger.py            # Rotating file logger
```

---

## 🚀 التثبيت المحلي

```bash
git clone https://github.com/YOUR_USERNAME/wbs-housing-bot.git
cd wbs-housing-bot

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# عدّل .env وأضف BOT_TOKEN و CHAT_ID

python main.py
```

---

## ⚙️ إعداد ملف .env

```env
BOT_TOKEN=123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxx
CHAT_ID=987654321

# اختياري
PROXY_URL=http://user:pass@host:port

# الفاصل الزمني بالدقائق
SCRAPE_INTERVAL=2

# الفلاتر الافتراضية
DEFAULT_MAX_PRICE=600
DEFAULT_ROOMS=
DEFAULT_AREA=
```

### كيف تحصل على BOT_TOKEN؟
1. افتح Telegram وابحث عن `@BotFather`
2. أرسل `/newbot`، اتبع التعليمات
3. انسخ الـ token

### كيف تحصل على CHAT_ID؟
1. ابحث عن `@userinfobot` في Telegram
2. أرسل `/start`
3. انسخ الرقم الظاهر

---

## 📱 أوامر البوت

| الأمر | الوصف |
|-------|-------|
| `/start` | بدء البوت وعرض المساعدة |
| `/status` | عرض الإعدادات الحالية |
| `/set_price 550` | تحديد أقصى إيجار |
| `/set_rooms 2` | أقل عدد غرف |
| `/set_area Spandau` | تحديد الحي |
| `/on` | تشغيل الإشعارات |
| `/off` | إيقاف الإشعارات |

---

## 🚂 الرفع على Railway

1. ارفع الكود على GitHub
2. اذهب إلى [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. اختر الـ repo
4. أضف المتغيرات من قسم Variables:
   - `BOT_TOKEN`
   - `CHAT_ID`
5. انتظر النشر ✅

---

## 🎨 شكل الإشعار

```
🏠 شقة جديدة — WBS مطلوب ⭐⭐⭐

📌 2-Zimmer-Wohnung in Spandau

📍 الموقع: Berlin-Spandau
💰 السعر: 520 €
🛏 عدد الغرف: 2
📄 مطلوب: WBS 100
🏢 المصدر: Gewobag 🏛

🔗 اضغط هنا لعرض الشقة
```

---

## 📝 ملاحظات

- المصادر الحكومية (Gewobag, Degewo, Howoge...) تأخذ تقييم أعلى ⭐⭐⭐
- الشقق القديمة تُحذف تلقائياً بعد 30 يوماً
- كل خطأ في scraper لا يوقف البقية
- السجلات تُحفظ في `logs/bot.log`
