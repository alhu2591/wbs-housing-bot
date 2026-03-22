#!/data/data/com.termux/files/usr/bin/bash
# ═══════════════════════════════════════════════════════════════
# WBS Housing Bot v2.0 — Termux Installation Script
# ═══════════════════════════════════════════════════════════════
# Run: bash install_termux.sh

set -e

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   🏠 WBS Housing Bot v2.0 — التثبيت         ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── 1. System packages ─────────────────────────────────────────
echo "📦 تحديث الحزم..."
pkg update -y && pkg upgrade -y
pkg install -y python git clang libffi openssl

# ── 2. Python packages ─────────────────────────────────────────
echo ""
echo "🐍 تثبيت مكتبات Python..."
pip install --upgrade pip

# Core
pip install python-telegram-bot httpx beautifulsoup4 apscheduler python-dotenv

# Dashboard (optional but recommended)
echo "🌐 تثبيت لوحة التحكم (fastapi + uvicorn)..."
pip install fastapi uvicorn || echo "⚠️  تعذر تثبيت fastapi — لوحة التحكم لن تعمل. يمكن تشغيل البوت بدونها."

echo ""
echo "✅ تم تثبيت جميع المكتبات"

# ── 3. .env setup ──────────────────────────────────────────────
echo ""
if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || touch .env
    echo "📝 ملف .env تم إنشاؤه"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  أدخل BOT_TOKEN (من @BotFather):"
    read -r BOT_TOKEN
    echo "  أدخل CHAT_ID (من @userinfobot):"
    read -r CHAT_ID
    echo "  أدخل ADMIN_CHAT_ID (اتركه فارغاً لاستخدام CHAT_ID):"
    read -r ADMIN_CHAT_ID

    {
        echo "BOT_TOKEN=${BOT_TOKEN}"
        echo "CHAT_ID=${CHAT_ID}"
        echo "ADMIN_CHAT_ID=${ADMIN_CHAT_ID:-$CHAT_ID}"
    } > .env
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "📝 ملف .env موجود بالفعل — لم يتم التغيير"
fi

# ── 4. Directories ─────────────────────────────────────────────
mkdir -p data logs
echo "📁 المجلدات جاهزة: data/ logs/"

# ── 5. DB init test ────────────────────────────────────────────
echo ""
echo "🗄️  تهيئة قاعدة البيانات..."
python -c "from database.db import init_db; init_db(); print('✅ قاعدة البيانات جاهزة')" 2>/dev/null || echo "⚠️  تعذر تهيئة قاعدة البيانات — ستتم عند أول تشغيل"

# ── 6. Done ────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║         ✅ التثبيت اكتمل بنجاح!             ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "🚀 لتشغيل البوت:"
echo "   python main.py"
echo ""
echo "🔇 للتشغيل في الخلفية:"
echo "   nohup python main.py > logs/output.log 2>&1 &"
echo ""
echo "📺 للتشغيل مع tmux (موصى به):"
echo "   pkg install tmux"
echo "   tmux new -s wbsbot"
echo "   python main.py"
echo "   # للفصل: Ctrl+B ثم D"
echo "   # للعودة: tmux attach -t wbsbot"
echo ""
echo "🌐 لوحة التحكم: http://localhost:8080"
echo "📊 الأوامر: /start  /settings  /status  /scan"
echo ""
