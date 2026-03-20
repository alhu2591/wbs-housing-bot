"""
p4a build hook — patches AndroidManifest.xml for Android 12-16.

CRITICAL fixes:
1. android:exported="true" on main Activity
   → Required since Android 12 (API 31). Without it: instant crash.
   
2. Remove any FOREGROUND_SERVICE_TYPE that isn't backed by a real
   Android Service (we use Python daemon threads, not Android Services)
   
3. tools:targetApi on uses-permission for POST_NOTIFICATIONS
   → Required since Android 13 (API 33)
"""
import os
import re


def _find_manifests(ctx):
    """Find all AndroidManifest.xml files in the build."""
    manifests = []
    search_dirs = [
        ctx.build_dir,
        os.path.join(ctx.build_dir, 'bootstrap_builds'),
        os.path.join(ctx.build_dir, 'dists'),
    ]
    for sd in search_dirs:
        for root, dirs, files in os.walk(sd):
            for f in files:
                if f == 'AndroidManifest.xml':
                    manifests.append(os.path.join(root, f))
    return manifests


def _patch_manifest(path):
    """Apply all Android 12-16 compat patches to a manifest."""
    try:
        content = open(path).read()
    except Exception:
        return

    original = content

    # Fix 1: Add android:exported="true" to main Activity if missing
    # The main SDL2 Activity MUST be exported so the launcher can start it
    content = re.sub(
        r'(<activity[^>]*org\.kivy\.android\.PythonActivity[^>]*?)(\s*/?>)',
        lambda m: (m.group(1) + ' android:exported="true"' + m.group(2))
                  if 'android:exported' not in m.group(1) else m.group(0),
        content, flags=re.DOTALL
    )

    # Fix 2: Add android:exported="true" to PythonService if present
    content = re.sub(
        r'(<service[^>]*PythonService[^>]*?)(\s*/?>)',
        lambda m: (m.group(1) + ' android:exported="false"' + m.group(2))
                  if 'android:exported' not in m.group(1) else m.group(0),
        content, flags=re.DOTALL
    )

    # Fix 3: Generic — add exported to any Activity/Service/Receiver missing it
    for tag in ['activity', 'service', 'receiver', 'provider']:
        default = '"true"' if tag in ('activity',) else '"false"'
        content = re.sub(
            rf'(<{tag}\b(?![^>]*android:exported)[^>]*?)(\s*/?>)',
            lambda m, d=default: m.group(1) + f' android:exported={d}' + m.group(2),
            content, flags=re.DOTALL
        )

    # Fix 4: POST_NOTIFICATIONS needs tools:targetApi="33" on Android 13+
    content = content.replace(
        'android.permission.POST_NOTIFICATIONS"',
        'android.permission.POST_NOTIFICATIONS" android:minSdkVersion="33"'
    )

    if content != original:
        open(path, 'w').write(content)
        print(f"[WBS hook] Patched: {path}")
    else:
        print(f"[WBS hook] No changes needed: {path}")


def prebuild_arch(manager, arch):
    """Called before each arch build."""
    pass


def postbuild_arch(manager, arch):
    """Called after each arch build — patch all manifests."""
    print("[WBS hook] Patching manifests for Android 12-16 compatibility...")
    try:
        manifests = _find_manifests(manager.ctx)
        print(f"[WBS hook] Found {len(manifests)} manifest(s)")
        for m in manifests:
            _patch_manifest(m)
    except Exception as e:
        print(f"[WBS hook] Warning: {e}")
