[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,ttf
version = 3.0.0

# arabic_reshaper + python-bidi: pure Python, fix Arabic squares
requirements = python3,kivy==2.3.0,beautifulsoup4,arabic-reshaper,python-bidi

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png

android.permissions = INTERNET,FOREGROUND_SERVICE,RECEIVE_BOOT_COMPLETED,VIBRATE,POST_NOTIFICATIONS
android.api = 33
android.minapi = 26
android.ndk = 25b
android.archs = arm64-v8a
android.allow_backup = True
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 0
