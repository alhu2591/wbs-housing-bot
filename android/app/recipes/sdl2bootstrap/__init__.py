"""
Patched SDL2 bootstrap recipe for Android 16 compatibility.
Patches AndroidManifest.xml to add:
  - android:exported="true" on all Activity/Service/Receiver
  - foregroundServiceType="dataSync" on all Service declarations
"""
import os
import re
from pythonforandroid.recipe import Recipe
from pythonforandroid.logger import info


def _patch_manifest(path):
    """Patch AndroidManifest.xml for Android 12-16 compatibility."""
    if not os.path.exists(path):
        return False
    
    content = open(path).read()
    original = content

    # 1. Add android:exported="true" to Activity if missing
    content = re.sub(
        r'(<activity\b(?![^>]*android:exported)[^>]*)(/>|>)',
        r'\1 android:exported="true"\2',
        content
    )

    # 2. Add android:exported="true" to Service if missing
    content = re.sub(
        r'(<service\b(?![^>]*android:exported)[^>]*)(/>|>)',
        r'\1 android:exported="false"\2',
        content
    )

    # 3. Add foregroundServiceType to Service declarations
    content = re.sub(
        r'(<service\b(?![^>]*foregroundServiceType)[^>]*)(/>|>)',
        r'\1 android:foregroundServiceType="dataSync"\2',
        content
    )

    # 4. Add android:exported to Receiver if missing
    content = re.sub(
        r'(<receiver\b(?![^>]*android:exported)[^>]*)(/>|>)',
        r'\1 android:exported="false"\2',
        content
    )

    if content != original:
        open(path, 'w').write(content)
        return True
    return False


class SDL2BootstrapPatch(Recipe):
    """Dummy recipe that just patches the manifest post-build."""
    name = 'sdl2bootstrap'
    url = None

    def build_arch(self, arch):
        pass

    def postbuild_arch(self, arch):
        info("[WBS] Patching AndroidManifest.xml for Android 12-16...")
        
        # Find the manifest
        possible = [
            os.path.join(self.ctx.build_dir, 'bootstrap_builds', 'sdl2',
                         'src', 'main', 'AndroidManifest.xml'),
            os.path.join(self.ctx.build_dir, 'dists', 'wbsberlin',
                         'src', 'main', 'AndroidManifest.xml'),
        ]
        
        for path in possible:
            if _patch_manifest(path):
                info(f"[WBS] Patched: {path}")
            elif os.path.exists(path):
                info(f"[WBS] Already OK: {path}")


recipe = SDL2BootstrapPatch()
