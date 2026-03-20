"""
p4a pre-build hook: ensures Cython generates .c files for Kivy
before the C compiler tries to compile them.
"""
def prebuild_arch(manager, arch):
    import subprocess, sys, os
    from pythonforandroid.logger import info

    # Ensure cython is available in the build environment
    try:
        import Cython
        info(f"Cython {Cython.__version__} available")
    except ImportError:
        info("Installing Cython...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "cython==0.29.33", "--quiet"])

    # Find kivy source and cythonize if .c files are missing
    kivy_build = os.path.join(
        manager.ctx.build_dir,
        "other_builds", "kivy",
        f"{arch.arch}__ndk_target_{manager.ctx.ndk_api}",
        "kivy",
    )
    event_c = os.path.join(kivy_build, "kivy", "_event.c")
    if os.path.isdir(kivy_build) and not os.path.exists(event_c):
        info("Cythonizing Kivy source files...")
        subprocess.call(
            [sys.executable, "setup.py", "build_ext", "--inplace"],
            cwd=kivy_build,
            env={**os.environ, "KIVY_NO_CONSOLELOG": "1"},
        )
