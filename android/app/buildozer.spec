[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,ttf
version = 5.2.0

# ONLY pure-Python pip packages — no p4a recipes that can conflict
requirements = python3,kivy==2.2.1,beautifulsoup4,arabic-reshaper,python-bidi

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png

android.permissions = INTERNET,FOREGROUND_SERVICE,VIBRATE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

# Build for BOTH 32-bit and 64-bit devices
android.archs = arm64-v8a, armeabi-v7a

android.api = 33
android.minapi = 21
android.ndk = 25b
android.ndk_api = 21
android.allow_backup = True
android.enable_androidx = True

p4a.local_recipes = ./recipes

[buildozer]
log_level = 2
warn_on_root = 0
