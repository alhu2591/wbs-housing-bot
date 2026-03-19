# WBS Berlin — Android App

تطبيق Android مستقل يجلب إعلانات الشقق المدعومة من برلين مباشرة.

## المميزات
- 🏛 10 مصادر (Gewobag, Degewo, Howoge, Gesobau, WBM, Vonovia...)
- 🎚 فلتر مستوى WBS (100 / 140 / 160 / 180 / 200 / 220)
- 💰 فلتر الإيجار والغرف والمساحة
- 🏛 فلتر Jobcenter KdU
- 📍 فلتر المناطق
- 🌐 تحديد المصادر
- 🔗 فتح الإعلان مباشرة

## تحميل APK
آخر نسخة: [Releases](https://github.com/alhu2591/wbs-housing-bot/releases)

## بناء يدوي (Linux/macOS)
```bash
cd android/app
pip install buildozer
buildozer android debug
# APK في: android/app/bin/WBSBerlin-1.0.0-debug.apk
```

## تشغيل على Android بدون APK (Termux)
```bash
pkg install python git clang libffi openssl
pip install kivy httpx beautifulsoup4 lxml
git clone https://github.com/alhu2591/wbs-housing-bot
cd wbs-housing-bot/android/app
python main.py
```
