#!/data/data/com.termux/files/usr/bin/bash
# start_bot.sh — Start or reattach the bot in tmux session
SESSION="wbsbot"
DIR="$(cd "$(dirname "$0")" && pwd)"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "🔄 البوت يعمل بالفعل — إعادة الاتصال..."
    tmux attach -t "$SESSION"
else
    echo "🚀 تشغيل البوت..."
    tmux new-session -d -s "$SESSION" -c "$DIR" "python main.py; exec bash"
    echo "✅ تم التشغيل في الخلفية (tmux session: $SESSION)"
    echo "📺 للعرض: tmux attach -t $SESSION"
    tmux attach -t "$SESSION"
fi
