"""
p4a hook for Android 12-16 (Samsung A53 + OneUI 8 + Android 16).
Patches AndroidManifest.xml to add android:exported attributes.
This is the #1 cause of black-screen-then-exit on Android 12+.
"""
import os
import re


def _patch_manifest(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return

    original = content

    # Add android:exported="true" to main PythonActivity
    def add_exported_activity(m):
        tag = m.group(0)
        if 'android:exported' not in tag:
            tag = tag.replace('<activity ', '<activity android:exported="true" ', 1)
        return tag

    content = re.sub(
        r'<activity\s[^>]*PythonActivity[^>]*/?>',
        add_exported_activity, content, flags=re.DOTALL
    )
    content = re.sub(
        r'<activity\s[^>]*PythonActivity[^>]*>.*?</activity>',
        add_exported_activity, content, flags=re.DOTALL
    )

    # Add exported=false to services/receivers missing it
    def add_exported_false(m):
        tag = m.group(0)
        if 'android:exported' not in tag:
            # Insert after the tag name
            tag = re.sub(r'(<(?:service|receiver|provider)\s)', r'\1android:exported="false" ', tag, count=1)
        return tag

    content = re.sub(
        r'<(?:service|receiver|provider)\s[^>]*/?>',
        add_exported_false, content, flags=re.DOTALL
    )

    if content != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'[WBS hook] Patched {os.path.basename(path)}')


def _find_and_patch(base_dir):
    count = 0
    for root, dirs, files in os.walk(base_dir):
        # Skip hidden dirs and node_modules
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in files:
            if fname == 'AndroidManifest.xml':
                _patch_manifest(os.path.join(root, fname))
                count += 1
    return count


def prebuild_arch(manager, arch):
    print('[WBS hook] prebuild_arch — patching manifests...')
    try:
        n = _find_and_patch(manager.ctx.build_dir)
        print(f'[WBS hook] Processed {n} manifest(s)')
    except Exception as e:
        print(f'[WBS hook] Warning (non-fatal): {e}')


def postbuild_arch(manager, arch):
    print('[WBS hook] postbuild_arch — re-patching manifests...')
    try:
        n = _find_and_patch(manager.ctx.build_dir)
        print(f'[WBS hook] Processed {n} manifest(s)')
    except Exception as e:
        print(f'[WBS hook] Warning (non-fatal): {e}')
