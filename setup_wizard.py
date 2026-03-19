"""
First-run setup wizard — sets BOT_TOKEN and CHAT_ID via interactive CLI.
Run once before starting the bot: python setup_wizard.py
"""
import os
import sys
import asyncio
import pathlib


def _env_file() -> pathlib.Path:
    return pathlib.Path(__file__).parent / ".env"


def _read_env() -> dict:
    env = {}
    f = _env_file()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _write_env(data: dict) -> None:
    lines = []
    for k, v in data.items():
        lines.append(f"{k}={v}")
    _env_file().write_text("\n".join(lines) + "\n", encoding="utf-8")


def _banner():
    print("\n" + "=" * 55)
    print("  🏠 WBS Housing Bot — Setup Wizard")
    print("=" * 55 + "\n")


async def _get_chat_id(token: str) -> str | None:
    """Send a test message and return the chat ID."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(f"https://api.telegram.org/bot{token}/getUpdates")
            data = resp.json()
            if not data.get("ok"): return None
            updates = data.get("result", [])
            if updates:
                msg = updates[-1].get("message") or updates[-1].get("callback_query", {}).get("message")
                if msg:
                    return str(msg["chat"]["id"])
    except Exception:
        pass
    return None


async def _verify_token(token: str) -> tuple[bool, str]:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(f"https://api.telegram.org/bot{token}/getMe")
            data = resp.json()
            if data.get("ok"):
                bot = data["result"]
                return True, f"@{bot['username']} ({bot['first_name']})"
            return False, data.get("description", "Invalid token")
    except Exception as e:
        return False, str(e)


async def run_setup():
    _banner()
    env = _read_env()

    print("ℹ️  سيطرح عليك هذا المعالج أسئلة لإعداد البوت.")
    print("   يمكن الضغط Enter للإبقاء على القيمة الحالية.\n")

    # ── BOT_TOKEN ──────────────────────────────────────────────────────────────
    current_token = env.get("BOT_TOKEN", "")
    if current_token:
        print(f"✅ BOT_TOKEN موجود: {current_token[:10]}...")
        change = input("   هل تريد تغييره؟ (y/N): ").strip().lower()
        if change != "y":
            token = current_token
        else:
            token = ""
    else:
        token = ""

    if not token:
        print()
        print("1️⃣  أنشئ بوت جديد عبر @BotFather على تيليجرام:")
        print("   /newbot → اتبع التعليمات → انسخ التوكن")
        while True:
            token = input("\n   BOT_TOKEN: ").strip()
            if not token: continue
            print("   🔍 جاري التحقق من التوكن...")
            ok, info = await _verify_token(token)
            if ok:
                print(f"   ✅ {info}")
                break
            else:
                print(f"   ❌ {info}")
                print("   حاول مرة أخرى.")

    # ── CHAT_ID ────────────────────────────────────────────────────────────────
    current_cid = env.get("CHAT_ID", "")
    if current_cid:
        print(f"\n✅ CHAT_ID موجود: {current_cid}")
        change = input("   هل تريد تغييره؟ (y/N): ").strip().lower()
        if change != "y":
            chat_id = current_cid
        else:
            chat_id = ""
    else:
        chat_id = ""

    if not chat_id:
        print()
        print("2️⃣  للحصول على CHAT_ID:")
        print("   أ) افتح @userinfobot أو @getidsbot على تيليجرام")
        print("   ب) أرسل له أي رسالة")
        print("   ج) انسخ الرقم 'your id'")
        print()
        print("   أو: أرسل رسالة لبوتك ثم أدخل /get_chat_id")
        print()
        while True:
            chat_id = input("   CHAT_ID: ").strip()
            if chat_id and (chat_id.lstrip("-").isdigit()):
                break
            print("   ❌ CHAT_ID يجب أن يكون رقماً (مثل: 123456789 أو -100123456789)")

    # ── Optional settings ──────────────────────────────────────────────────────
    print("\n3️⃣  إعدادات اختيارية (Enter للتخطي):\n")

    interval = env.get("SCRAPE_INTERVAL", "5")
    new_interval = input(f"   فترة البحث بالدقائق [{interval}]: ").strip()
    if new_interval and new_interval.isdigit():
        interval = new_interval

    max_price = env.get("DEFAULT_MAX_PRICE", "600")
    new_price = input(f"   أقصى إيجار افتراضي (€) [{max_price}]: ").strip()
    if new_price and new_price.isdigit():
        max_price = new_price

    data_dir = env.get("DATA_DIR", "")
    print(f"   مجلد البيانات [{data_dir or 'مجلد المشروع'}]: ", end="")
    new_dir = input("").strip()
    if new_dir:
        data_dir = new_dir

    # ── Write .env ─────────────────────────────────────────────────────────────
    new_env = {
        "BOT_TOKEN":        token,
        "CHAT_ID":          chat_id,
        "SCRAPE_INTERVAL":  interval,
        "DEFAULT_MAX_PRICE": max_price,
    }
    if data_dir:
        new_env["DATA_DIR"] = data_dir

    _write_env(new_env)

    print("\n" + "=" * 55)
    print("✅ تم حفظ الإعدادات في ملف .env")
    print()
    print("لتشغيل البوت:")
    print("  python run_local.py")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(run_setup())
    except KeyboardInterrupt:
        print("\n\nتم الإلغاء.")
