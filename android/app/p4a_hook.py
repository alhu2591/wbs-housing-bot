"""
p4a hook — patches AndroidManifest.xml for Android 12-16 compatibility.

THE main fix for black-screen-then-exit on Samsung A53 + Android 16:
  android:exported="true" MUST be on the main Activity since Android 12 (API 31).
  p4a 2022.x does NOT set this. Result without it: instant crash on all Android 12+ devices.

Also fixes Services/Receivers missing android:exported (causes warnings on Android 12+).

Called by p4a as: prebuild_arch(manager, arch) and postbuild_arch(manager, arch)
"""
import os
import re


def _patch_manifest(path):
    """Patch one AndroidManifest.xml file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return

    original = content

    # ── Fix 1: Add android:exported="true" to main PythonActivity ──────
    # This is MANDATORY on Android 12+ (API 31+) for the app to launch.
    # The attribute must be set on any Activity that has an <intent-filter>.

    def _fix_activity(m):
        tag = m.group(0)
        if 'android:exported' not in tag:
            tag = re.sub(r'(<activity\b\s)', r'\1android:exported="true" ', tag, count=1)
        return tag

    # Handle both self-closing and block activity tags
    content = re.sub(r'<activity\b[^>]*/>', _fix_activity, content)
    content = re.sub(r'<activity\b[\s\S]*?</activity>', _fix_activity, content)

    # ── Fix 2: Add android:exported="false" to Services, Receivers, Providers ──
    # Required since Android 12. Default behaviour changed — must be explicit.

    def _fix_component(m):
        tag = m.group(0)
        tag_name = re.match(r'<(\w+)', tag).group(1)
        if 'android:exported' not in tag:
            tag = re.sub(
                r'(<' + tag_name + r'\b\s)',
                r'\1android:exported="false" ',
                tag, count=1
            )
        return tag

    content = re.sub(r'<(?:service|receiver|provider)\b[^>]*/>', _fix_component, content)
    content = re.sub(r'<(?:service|receiver|provider)\b[\s\S]*?</(?:service|receiver|provider)>', _fix_component, content)

    if content != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'[WBS hook] Patched: {os.path.relpath(path)}')
    else:
        print(f'[WBS hook] Already OK: {os.path.relpath(path)}')


def _run(ctx):
    """Find and patch all manifests in the build directory."""
    patched = 0
    for root, dirs, files in os.walk(ctx.build_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in files:
            if fname == 'AndroidManifest.xml':
                _patch_manifest(os.path.join(root, fname))
                patched += 1
    print(f'[WBS hook] Processed {patched} manifest(s)')


def prebuild_arch(manager, arch):
    print('[WBS hook] prebuild_arch: patching manifests...')
    try:
        _run(manager.ctx)
    except Exception as e:
        print(f'[WBS hook] Warning: {e}')


def postbuild_arch(manager, arch):
    print('[WBS hook] postbuild_arch: re-patching manifests...')
    try:
        _run(manager.ctx)
    except Exception as e:
        print(f'[WBS hook] Warning: {e}')
