[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,ttf
version = 5.3.1

requirements = python3,kivy==2.2.1,beautifulsoup4,arabic-reshaper,python-bidi

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png

# MINIMAL permissions — no FOREGROUND_SERVICE (we use daemon threads, not Android Services)
# Declaring FOREGROUND_SERVICE without calling startForegroundService() crashes on Android 14+
android.permissions = INTERNET,VIBRATE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

# API 34 for Android 14/15/16 compat
android.api = 34
android.minapi = 23
android.ndk = 25b
android.ndk_api = 23
android.archs = arm64-v8a

# CRITICAL: android.exported fix for Android 12+ (API 31+)
# Without this, app crashes with "App has not been exported" on Android 12+
android.manifest.activity_attributes = android:exported="true"

android.allow_backup = True
android.enable_androidx = True

# Hook to patch AndroidManifest.xml after p4a generates it
p4a.hook = p4a_hook.py
p4a.local_recipes = ./recipes

[buildozer]
log_level = 2
warn_on_root = 0
