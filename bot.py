import os
import threading
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "users.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0,
            referred_by INTEGER DEFAULT NULL,
            referral_count INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def add_user(user, referred_by=None):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    )

    if cur.fetchone() is None:
        cur.execute("""
            INSERT INTO users
            (user_id, username, first_name, balance, referred_by)
            VALUES (?, ?, ?, 0, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            referred_by
        ))

        if referred_by and referred_by != user.id:
            cur.execute("""
                UPDATE users
                SET referral_count = referral_count + 1
                WHERE user_id = ?
            """, (referred_by,))

    conn.commit()
    conn.close()


def get_balance(user_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute(
        "SELECT balance FROM users WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchone()
    conn.close()

    return result[0] if result else 0


def get_referrals(user_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute(
        "SELECT referral_count FROM users WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchone()
    conn.close()

    return result[0] if result else 0


class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"EHAN EARN BOT is running!")

    def log_message(self, format, *args):
        return


def start_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    referred_by = None

    if context.args:
        try:
            referred_by = int(context.args[0])
        except ValueError:
            referred_by = None

    add_user(update.effective_user, referred_by)

    await update.message.reply_text(
        "🎉 Welcome to EHAN EARN BOT!\n\n"
        "আপনার অ্যাকাউন্ট তৈরি হয়েছে।\n\n"
        "📌 Menu:\n"
        "/balance - আপনার Balance\n"
        "/quiz - International Quiz\n"
        "/mining - Virtual Mining\n"
        "/tasks - Available Tasks\n"
        "/referral - Referral Link\n"
        "/games - Games\n"
        "/withdraw - Withdrawal\n"
        "/leaderboard - Leaderboard\n"
        "/rules - Bot Rules\n"
        "/help - Help"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):

    add_user(update.effective_user)

    amount = get_balance(update.effective_user.id)

    await update.message.reply_text(
        f"💰 আপনার Balance: {amount:.2f} Points"
    )


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):

    add_user(update.effective_user)

    user_id = update.effective_user.id
    count = get_referrals(user_id)

    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={user_id}"

    await update.message.reply_text(
        "👥 Referral System\n\n"
        f"🔗 আপনার Referral Link:\n{link}\n\n"
        f"👤 Total Referrals: {count}\n\n"
        "আপনার Referral Link অন্যদের সাথে শেয়ার করুন।"
    )


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌍 International Quiz\n\n"
        "Quiz system শীঘ্রই চালু হবে।"
    )


async def mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⛏️ Virtual Mining\n\n"
        "Mining system শীঘ্রই চালু হবে।"
    )


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Available Tasks\n\n"
        "বর্তমানে কোনো Task নেই।"
    )


async def games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 Games\n\n"
        "Games system শীঘ্রই চালু হবে।"
    )


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💸 Withdrawal\n\n"
        "Withdrawal system শীঘ্রই চালু হবে।"
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏆 Leaderboard\n\n"
        "Leaderboard শীঘ্রই চালু হবে।"
    )


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📜 BOT RULES\n\n"
        "• Fake account ব্যবহার করবেন না।\n"
        "• প্রতারণামূলক কাজ করা যাবে না।\n"
        "• Withdrawal-এর আগে প্রয়োজনীয় শর্ত পূরণ করতে হবে।"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 Help\n\n"
        "যেকোনো সমস্যায় Admin-এর সাথে যোগাযোগ করুন।"
    )


def main():

    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing.")

    init_db()

    threading.Thread(
        target=start_web_server,
        daemon=True
    ).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CommandHandler("mining", mining))
    app.add_handler(CommandHandler("tasks", tasks))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("games", games))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("help", help_command))

    print("EHAN EARN BOT is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
