[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 4.0.0

# kivy 2.2.1 + cython 0.29.33 = last known-good stable combination
# arabic-reshaper + python-bidi are pure Python (no C compilation needed)
requirements = python3,kivy==2.2.1,cython==0.29.33,beautifulsoup4,arabic-reshaper,python-bidi

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

# Force Cython to generate .c files before Kivy compiles
p4a.hook = pre_build_hook.py

[buildozer]
log_level = 2
warn_on_root = 0
