import os
import sqlite3
import threading
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# Render Environment Variable-এ ADMIN_ID সেট করতে পারবেন।
# না দিলে Admin system ব্যবহার হবে না।
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "users.db"

# Mining settings
MINING_REWARD = 5
MINING_COOLDOWN_HOURS = 1

# Referral reward
REFERRAL_REWARD = 10


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0,
            referred_by INTEGER DEFAULT NULL,
            referral_count INTEGER DEFAULT 0,
            last_mining TEXT DEFAULT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            method TEXT,
            account TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# USER SYSTEM
# =========================================================

def add_user(user, referred_by=None):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    )

    existing = cur.fetchone()

    if existing is None:

        cur.execute("""
            INSERT INTO users
            (
                user_id,
                username,
                first_name,
                balance,
                referred_by
            )
            VALUES (?, ?, ?, 0, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            referred_by
        ))

        # Referral reward
        if referred_by and referred_by != user.id:

            cur.execute("""
                UPDATE users
                SET referral_count = referral_count + 1,
                    balance = balance + ?
                WHERE user_id = ?
            """, (
                REFERRAL_REWARD,
                referred_by
            ))

    else:

        cur.execute("""
            UPDATE users
            SET username=?,
                first_name=?
            WHERE user_id=?
        """, (
            user.username or "",
            user.first_name or "",
            user.id
        ))

    conn.commit()
    conn.close()


def get_balance(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT balance FROM users WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchone()

    conn.close()

    return result["balance"] if result else 0


def add_balance(user_id, amount):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET balance = balance + ?
        WHERE user_id = ?
    """, (
        amount,
        user_id
    ))

    conn.commit()
    conn.close()


def get_referrals(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT referral_count FROM users WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchone()

    conn.close()

    return result["referral_count"] if result else 0


# =========================================================
# HEALTH SERVER FOR RENDER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)
        self.send_header(
            "Content-type",
            "text/plain"
        )
        self.end_headers()

        self.wfile.write(
            b"EHAN EARN BOT is running!"
        )

    def log_message(self, format, *args):
        return


def start_web_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    server.serve_forever()


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    referred_by = None

    if context.args:

        try:
            referred_by = int(context.args[0])

        except ValueError:
            referred_by = None

    add_user(
        update.effective_user,
        referred_by
    )

    await update.message.reply_text(
        "🎉 Welcome to EHAN EARN BOT!\n\n"
        "আপনার অ্যাকাউন্ট তৈরি হয়েছে।\n\n"
        "📌 Menu:\n\n"
        "/balance - 💰 Balance\n"
        "/mining - ⛏️ Mining\n"
        "/quiz - 🌍 Quiz\n"
        "/tasks - 📋 Tasks\n"
        "/referral - 👥 Referral\n"
        "/games - 🎮 Games\n"
        "/leaderboard - 🏆 Leaderboard\n"
        "/withdraw - 💸 Withdrawal\n"
        "/rules - 📜 Rules\n"
        "/help - 🆘 Help"
    )


# =========================================================
# BALANCE
# =========================================================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    amount = get_balance(
        update.effective_user.id
    )

    await update.message.reply_text(
        f"💰 আপনার Balance: {amount:.2f} Points"
    )


# =========================================================
# REFERRAL
# =========================================================

async def referral(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    user_id = update.effective_user.id

    count = get_referrals(user_id)

    bot_username = context.bot.username

    link = (
        f"https://t.me/"
        f"{bot_username}"
        f"?start={user_id}"
    )

    await update.message.reply_text(
        "👥 REFERRAL SYSTEM\n\n"
        f"🔗 আপনার Referral Link:\n"
        f"{link}\n\n"
        f"👤 Total Referrals: {count}\n"
        f"🎁 প্রতি নতুন Referral Reward: "
        f"{REFERRAL_REWARD} Points\n\n"
        "আপনার লিংক বন্ধুদের সাথে শেয়ার করুন।"
    )


# =========================================================
# MINING
# =========================================================

async def mining(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    add_user(update.effective_user)

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT last_mining FROM users WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchone()

    last_mining = (
        result["last_mining"]
        if result
        else None
    )

    now = datetime.utcnow()

    if last_mining:

        try:

            last_time = datetime.fromisoformat(
                last_mining
            )

            next_time = (
                last_time +
                timedelta(hours=MINING_COOLDOWN_HOURS)
            )

            if now < next_time:

                remaining = next_time - now

                minutes = int(
                    remaining.total_seconds() // 60
                )

                await update.message.reply_text(
                    "⛏️ Mining চলছে!\n\n"
                    f"⏳ আবার Mining করতে "
                    f"{minutes} মিনিট অপেক্ষা করুন।"
                )

                conn.close()
                return

        except Exception:
            pass

    cur.execute("""
        UPDATE users
        SET balance = balance + ?,
            last_mining = ?
        WHERE user_id = ?
    """, (
        MINING_REWARD,
        now.isoformat(),
        user_id
    ))

    conn.commit()
    conn.close()

    new_balance = get_balance(user_id)

    await update.message.reply_text(
        "⛏️ MINING SUCCESSFUL!\n\n"
        f"🎁 Mining Reward: "
        f"+{MINING_REWARD} Points\n\n"
        f"💰 Current Balance: "
        f"{new_balance:.2f} Points\n\n"
        f"⏳ আবার Mining করতে "
        f"{MINING_COOLDOWN_HOURS} ঘণ্টা পরে আসুন।"
    )


# =========================================================
# QUIZ
# =========================================================

QUIZ_DATA = [

    (
        "🌍 What is the capital of Bangladesh?",
        ["Dhaka", "Chattogram", "Rajshahi", "Sylhet"],
        "Dhaka"
    ),

    (
        "🌍 Which planet is known as the Red Planet?",
        ["Earth", "Mars", "Jupiter", "Venus"],
        "Mars"
    ),

    (
        "🌍 How many days are there in a week?",
        ["5", "6", "7", "8"],
        "7"
    ),

]


async def quiz(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    question, options, answer = random.choice(
        QUIZ_DATA
    )

    text = (
        "🌍 INTERNATIONAL QUIZ\n\n"
        f"{question}\n\n"
        f"A) {options[0]}\n"
        f"B) {options[1]}\n"
        f"C) {options[2]}\n"
        f"D) {options[3]}\n\n"
        "সঠিক উত্তর দেখতে Admin/Quiz system ব্যবহার করুন।"
    )

    await update.message.reply_text(text)


# =========================================================
# TASKS
# =========================================================

async def tasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "📋 AVAILABLE TASKS\n\n"
        "বর্তমানে কোনো Task available নেই।\n\n"
        "নতুন Task যোগ হলে এখানে দেখানো হবে।"
    )


# =========================================================
# GAMES
# =========================================================

async def games(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎮 GAMES\n\n"
        "🎲 Number Guess Game\n"
        "🧩 Quiz Game\n"
        "🎯 আরও Game শীঘ্রই যোগ হবে।"
    )


# =========================================================
# LEADERBOARD
# =========================================================

async def leaderboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT first_name, username, balance
        FROM users
        ORDER BY balance DESC
        LIMIT 10
    """)

    users = cur.fetchall()

    conn.close()

    if not users:

        await update.message.reply_text(
            "🏆 এখনো কোনো User নেই।"
        )

        return

    text = "🏆 TOP 10 LEADERBOARD\n\n"

    for index, user in enumerate(users, 1):

        name = (
            user["first_name"]
            or user["username"]
            or "User"
        )

        text += (
            f"{index}. {name} — "
            f"{user['balance']:.2f} Points\n"
        )

    await update.message.reply_text(text)


# =========================================================
# WITHDRAW
# =========================================================

async def withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    balance_amount = get_balance(
        update.effective_user.id
    )

    await update.message.reply_text(
        "💸 WITHDRAWAL\n\n"
        f"💰 আপনার Balance: "
        f"{balance_amount:.2f} Points\n\n"
        "Withdrawal system এখনো সম্পূর্ণভাবে "
        "চালু করা হয়নি।\n\n"
        "পরবর্তী ধাপে আমরা:\n"
        "• Minimum withdrawal\n"
        "• Payment method\n"
        "• Account number\n"
        "• Withdrawal request\n"
        "• Admin approval\n"
        "যোগ করব।"
    )


# =========================================================
# RULES
# =========================================================

async def rules(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "📜 EHAN EARN BOT RULES\n\n"
        "1️⃣ Fake account ব্যবহার করবেন না।\n"
        "2️⃣ একই ব্যক্তির একাধিক account ব্যবহার "
        "করা যাবে না।\n"
        "3️⃣ কোনো প্রতারণামূলক কাজ করা যাবে না।\n"
        "4️⃣ Referral abuse করা যাবে না।\n"
        "5️⃣ Withdrawal-এর ক্ষেত্রে প্রয়োজনীয় "
        "শর্ত পূরণ করতে হবে।\n\n"
        "⚠️ Points-এর কোনো cash value নিশ্চিত নয় "
        "যতক্ষণ না official withdrawal system "
        "চালু করা হয়।"
    )


# =========================================================
# HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🆘 EHAN EARN BOT HELP\n\n"
        "/start — Start Bot\n"
        "/balance — Balance দেখুন\n"
        "/mining — Mining করুন\n"
        "/quiz — Quiz\n"
        "/tasks — Tasks\n"
        "/referral — Referral Link\n"
        "/games — Games\n"
        "/leaderboard — Top Users\n"
        "/withdraw — Withdrawal\n"
        "/rules — Rules\n"
        "/help — Help\n\n"
        "সমস্যা হলে Admin-এর সাথে যোগাযোগ করুন।"
    )


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id):

    return (
        ADMIN_ID != 0
        and user_id == ADMIN_ID
    )


async def admin_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ আপনি Admin নন।"
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) AS total FROM users"
    )

    total_users = cur.fetchone()["total"]

    cur.execute(
        "SELECT SUM(balance) AS total FROM users"
    )

    total_balance = cur.fetchone()["total"] or 0

    cur.execute(
        "SELECT COUNT(*) AS total FROM withdrawals "
        "WHERE status='Pending'"
    )

    pending = cur.fetchone()["total"]

    conn.close()

    await update.message.reply_text(
        "👨‍💻 ADMIN STATISTICS\n\n"
        f"👥 Total Users: {total_users}\n"
        f"💰 Total Points: {total_balance:.2f}\n"
        f"💸 Pending Withdrawals: {pending}"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    init_db()

    threading.Thread(
        target=start_web_server,
        daemon=True
    ).start()

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # Main commands
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("balance", balance)
    )

    app.add_handler(
        CommandHandler("referral", referral)
    )

    app.add_handler(
        CommandHandler("mining", mining)
    )

    app.add_handler(
        CommandHandler("quiz", quiz)
    )

    app.add_handler(
        CommandHandler("tasks", tasks)
    )

    app.add_handler(
        CommandHandler("games", games)
    )

    app.add_handler(
        CommandHandler("leaderboard", leaderboard)
    )

    app.add_handler(
        CommandHandler("withdraw", withdraw)
    )

    app.add_handler(
        CommandHandler("rules", rules)
    )

    app.add_handler(
        CommandHandler("help", help_command)
    )

    # Admin
    app.add_handler(
        CommandHandler("adminstats", admin_stats)
    )

    print("EHAN EARN BOT is running...")

    app.run_polling()


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":
    main()
