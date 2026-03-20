[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,ttf
version = 5.3.0

# Pure Python only — no extra recipes that can conflict
requirements = python3,kivy==2.2.1,beautifulsoup4,arabic-reshaper,python-bidi

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png

# Android 14+ (API 34): FOREGROUND_SERVICE must declare type
# Otherwise the service is KILLED on Android 14+ before app even starts
android.permissions = INTERNET,FOREGROUND_SERVICE,FOREGROUND_SERVICE_DATA_SYNC,VIBRATE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED,WAKE_LOCK

# Target API 34 for Android 14/15/16 compatibility
android.api = 34
android.minapi = 23
android.ndk = 25b
android.ndk_api = 23
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True
android.enable_androidx = True

# Required for Android 12+ (API 31+): explicit exported flag
android.manifest.intent_filters_xml =

p4a.local_recipes = ./recipes

[buildozer]
log_level = 2
warn_on_root = 0
