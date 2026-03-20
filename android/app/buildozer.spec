[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,ttf
version = 8.0.0

requirements = python3,kivy==2.2.1,beautifulsoup4,arabic-reshaper,python-bidi

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png

android.permissions = INTERNET,VIBRATE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

android.api = 34
android.minapi = 23
android.ndk = 25b
android.ndk_api = 23
android.archs = arm64-v8a

android.allow_backup = True
android.enable_androidx = True

p4a.hook = p4a_hook.py
p4a.local_recipes = ./recipes

[buildozer]
log_level = 2
warn_on_root = 0
