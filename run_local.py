"""
Local runner — start the bot from your computer.
Works on Windows, macOS, Linux.

Usage:
    python run_local.py

Requirements:
    pip install -r requirements.txt
    Copy .env.example → .env and fill in BOT_TOKEN + CHAT_ID
"""
import sys
import os
import asyncio
import pathlib

# ── Pre-flight checks ─────────────────────────────────────────────────────────

def check_env():
    env_file = pathlib.Path(".env")
    if not env_file.exists():
        example = pathlib.Path(".env.example")
        if example.exists():
            import shutil
            shutil.copy(example, env_file)
            print("✅ Created .env from .env.example")
            print("⚠️  Please edit .env and add your BOT_TOKEN and CHAT_ID")
            print("   Then run again: python run_local.py")
            sys.exit(0)
        else:
            print("❌ No .env file found. Create one with BOT_TOKEN and CHAT_ID")
            sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv()
    missing = [v for v in ("BOT_TOKEN", "CHAT_ID") if not os.getenv(v)]
    if missing:
        print(f"❌ Missing in .env: {', '.join(missing)}")
        print("   Edit .env and add your values, then run again.")
        sys.exit(1)
    print("✅ .env loaded")


def check_python():
    if sys.version_info < (3, 11):
        print(f"❌ Python 3.11+ required, you have {sys.version}")
        sys.exit(1)
    print(f"✅ Python {sys.version.split()[0]}")


def check_deps():
    missing = []
    for pkg, import_name in [
        ("python-telegram-bot", "telegram"),
        ("httpx",               "httpx"),
        ("beautifulsoup4",      "bs4"),
        ("aiosqlite",           "aiosqlite"),
        ("apscheduler",         "apscheduler"),
        ("python-dotenv",       "dotenv"),
        ("lxml",                "lxml"),
    ]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"❌ Missing packages: {', '.join(missing)}")
        print(f"   Run: pip install {' '.join(missing)}")
        sys.exit(1)
    print("✅ Dependencies OK")


def set_local_defaults():
    """Set DATA_DIR to project root for local storage."""
    if not os.getenv("DATA_DIR"):
        os.environ["DATA_DIR"] = str(pathlib.Path(__file__).parent)
    print(f"✅ Data directory: {os.environ['DATA_DIR']}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🏠 WBS Housing Bot — Local Runner")
    print("=" * 40)

    check_python()
    check_deps()
    check_env()
    set_local_defaults()

    print("\n🚀 Starting bot... (Ctrl+C to stop)\n")

    # Windows fix: asyncio event loop policy
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Import and run main
    from main import main
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Stopped.")
