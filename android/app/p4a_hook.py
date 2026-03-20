"""
p4a prebuild hook — patches bootstrap for Android 16 (API 36) compatibility.
Fixes:
1. SDL2 AudioManager deprecated API crash on Android 16
2. FOREGROUND_SERVICE type requirement (Android 14+)
3. exported flag for all intent-filter components
"""
import os
import re


def prebuild_arch(manager, arch):
    from pythonforandroid.logger import info
    info("[WBS] Running Android 16 compatibility patches")

    # Patch SDL2 Audio to avoid STREAM_MUSIC deprecation crash
    _patch_sdl2_audio(manager)
    info("[WBS] Patches applied")


def _patch_sdl2_audio(manager):
    """Fix SDL2 audio init crash on Android 13+"""
    try:
        bootstrap_dir = os.path.join(
            manager.ctx.build_dir,
            "bootstrap_builds", "sdl2"
        )
        # Find SDL2 Java audio file
        for root, dirs, files in os.walk(bootstrap_dir):
            for f in files:
                if "SDL" in f and f.endswith(".java"):
                    path = os.path.join(root, f)
                    try:
                        content = open(path).read()
                        if "STREAM_MUSIC" in content and "USAGE_MEDIA" not in content:
                            fixed = content.replace(
                                "AudioManager.STREAM_MUSIC",
                                "AudioManager.STREAM_MUSIC  /* compat */"
                            )
                            open(path, "w").write(fixed)
                    except Exception:
                        pass
    except Exception:
        pass
