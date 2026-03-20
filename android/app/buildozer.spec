[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 4.0.0

# IMPORTANT: NO cython in requirements.
# Cython is a host build tool, NOT a cross-compiled Android library.
# Our custom recipes/kivy downloads from PyPI (has pre-generated .c files).
requirements = python3,kivy==2.2.1,beautifulsoup4,arabic-reshaper,python-bidi

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png

android.permissions = INTERNET,FOREGROUND_SERVICE,VIBRATE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED
android.api = 33
android.minapi = 26
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.allow_backup = True
android.enable_androidx = True

# Use our patched recipe that downloads from PyPI (includes pre-built .c files)
p4a.local_recipes = ./recipes

[buildozer]
log_level = 2
warn_on_root = 0
