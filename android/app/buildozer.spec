[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json

version = 1.0.0

# Only what's needed — fewer deps = faster build + fewer failures
requirements = python3==3.11.6,kivy==2.3.0,httpx,beautifulsoup4,lxml,certifi,charset-normalizer,idna,anyio,sniffio,httpcore,h11

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png

android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.allow_backup = True
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 0
