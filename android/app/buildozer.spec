[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,ttf
version = 5.4.0

# Pure Python pip packages only
requirements = python3,kivy==2.2.1,beautifulsoup4,arabic-reshaper,python-bidi

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png

# Permissions: no FOREGROUND_SERVICE (uses Python threads, not Android Service)
android.permissions = INTERNET,VIBRATE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

# Target API 34 = Android 14 compat APIs active
android.api = 34
android.minapi = 23
android.ndk = 25b
android.ndk_api = 23
android.archs = arm64-v8a

# Android 12+ fix: force exported=true on main Activity
android.manifest.activity_attributes = android:exported="true"

android.allow_backup = True
android.enable_androidx = True

# Hook runs pre AND post build to patch android:exported on all manifests
p4a.hook = p4a_hook.py
# Custom Kivy recipe: downloads from PyPI sdist (has pre-built .c files)
p4a.local_recipes = ./recipes

[buildozer]
log_level = 2
warn_on_root = 0
