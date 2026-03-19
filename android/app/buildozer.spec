[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 1.0.0

# Pure Python only — no C extensions
requirements = python3,kivy==2.3.0,beautifulsoup4

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png

android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.ndk = 25.2.9519653
android.ndk_api = 24
android.sdk = 33
android.build_tools_version = 33.0.2
android.archs = arm64-v8a
android.allow_backup = True
android.enable_androidx = True
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
