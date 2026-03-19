[app]
title = WBS Berlin
package.name = wbsberlin
package.domain = de.alaa.wbs
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 1.0.0

# Pure Python — no C compilation needed
requirements = python3,kivy==2.3.0,beautifulsoup4

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png

android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.allow_backup = True
android.enable_androidx = True

# Force stable build-tools (not rc2 which needs separate license)
android.build_tools_version = 33.0.2

# Auto-accept SDK licenses
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
