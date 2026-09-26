import os
import sqlite3
import threading
import random
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# Render Environment Variables থেকে নেওয়া হবে
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "users.db"

# Rewards
MINING_REWARD = 5
MINING_COOLDOWN_HOURS = 1

REFERRAL_REWARD = 10
QUIZ_REWARD = 5
DAILY_REWARD = 10

# Game
GAME_REWARD = 10

# Withdrawal
MIN_WITHDRAWAL = 100


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table, column):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    columns = [row["name"] for row in cur.fetchall()]
    return column in columns


def add_column_if_missing(conn, table, column, definition):

    if not column_exists(conn, table, column):

        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN "
            f"{column} {definition}"
        )


def init_db():

    conn = get_db()
    cur = conn.cursor()

    # Users
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

    # পুরোনো database থাকলেও নতুন column যোগ হবে
    add_column_if_missing(
        conn,
        "users",
        "last_daily",
        "TEXT DEFAULT NULL"
    )

    # Withdrawals
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

    # Tasks
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            reward REAL DEFAULT 0,
            active INTEGER DEFAULT 1
        )
    """)

    # Task submissions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task_id INTEGER,
            status TEXT DEFAULT 'Pending',
            created_at TEXT
        )
    """)

    # Games
    cur.execute("""
        CREATE TABLE IF NOT EXISTS game_stats (
            user_id INTEGER PRIMARY KEY,
            wins INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# USER
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

        # নিজের referral link নিজে ব্যবহার করতে পারবে না
        if referred_by == user.id:
            referred_by = None

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
        if referred_by:

            cur.execute(
                "SELECT user_id FROM users WHERE user_id=?",
                (referred_by,)
            )

            referrer_exists = cur.fetchone()

            if referrer_exists:

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

    return float(result["balance"]) if result else 0


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


def subtract_balance(user_id, amount):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET balance = balance - ?
        WHERE user_id = ?
          AND balance >= ?
    """, (
        amount,
        user_id,
        amount
    ))

    success = cur.rowcount > 0

    conn.commit()
    conn.close()

    return success


def get_referrals(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT referral_count FROM users WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchone()

    conn.close()

    return int(result["referral_count"]) if result else 0


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


# =========================================================
# RENDER HEALTH SERVER
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
        "📌 MAIN MENU\n\n"
        "💰 /balance - Balance\n"
        "⛏️ /mining - Mining\n"
        "🎁 /daily - Daily Bonus\n"
        "🌍 /quiz - Quiz\n"
        "📋 /tasks - Tasks\n"
        "👥 /referral - Referral\n"
        "🎮 /games - Games\n"
        "🏆 /leaderboard - Leaderboard\n"
        "💸 /withdraw - Withdrawal\n"
        "🆔 /myid - My ID\n"
        "📜 /rules - Rules\n"
        "🆘 /help - Help"
    )


# =========================================================
# BALANCE
# =========================================================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):

    add_user(update.effective_user)

    amount = get_balance(
        update.effective_user.id
    )

    await update.message.reply_text(
        "💰 YOUR BALANCE\n\n"
        f"💵 Balance: {amount:.2f} Points"
    )


# =========================================================
# REFERRAL
# =========================================================

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
        f"🎁 প্রতি নতুন Referral: "
        f"+{REFERRAL_REWARD} Points\n\n"
        "আপনার লিংক বন্ধুদের সাথে শেয়ার করুন।"
    )


# =========================================================
# MINING
# =========================================================

async def mining(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
                    "⛏️ MINING COOLDOWN\n\n"
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
        f"🎁 Reward: +{MINING_REWARD} Points\n"
        f"💰 Balance: {new_balance:.2f} Points\n\n"
        f"⏳ আবার Mining করতে "
        f"{MINING_COOLDOWN_HOURS} ঘণ্টা পরে আসুন।"
    )


# =========================================================
# DAILY BONUS
# =========================================================

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    add_user(update.effective_user)

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT last_daily FROM users WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchone()

    last_daily = (
        result["last_daily"]
        if result
        else None
    )

    today = datetime.utcnow().date()

    if last_daily:

        try:

            last_date = datetime.fromisoformat(
                last_daily
            ).date()

            if last_date == today:

                await update.message.reply_text(
                    "🎁 DAILY BONUS\n\n"
                    "আপনি আজকের Daily Bonus ইতিমধ্যে নিয়েছেন।\n"
                    "আগামীকাল আবার নিতে পারবেন।"
                )

                conn.close()
                return

        except Exception:
            pass

    cur.execute("""
        UPDATE users
        SET balance = balance + ?,
            last_daily = ?
        WHERE user_id = ?
    """, (
        DAILY_REWARD,
        datetime.utcnow().isoformat(),
        user_id
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🎁 DAILY BONUS RECEIVED!\n\n"
        f"+{DAILY_REWARD} Points\n\n"
        f"💰 Balance: "
        f"{get_balance(user_id):.2f} Points\n\n"
        "আগামীকাল আবার Daily Bonus নিতে পারবেন।"
    )


# =========================================================
# QUIZ
# =========================================================

QUIZ_DATA = [

    {
        "question": "🌍 What is the capital of Bangladesh?",
        "options": [
            "Dhaka",
            "Chattogram",
            "Rajshahi",
            "Sylhet"
        ],
        "answer": 0
    },

    {
        "question": "🌍 Which planet is known as the Red Planet?",
        "options": [
            "Earth",
            "Mars",
            "Jupiter",
            "Venus"
        ],
        "answer": 1
    },

    {
        "question": "🌍 How many days are there in a week?",
        "options": [
            "5",
            "6",
            "7",
            "8"
        ],
        "answer": 2
    },

    {
        "question": "🌍 Which is the largest ocean?",
        "options": [
            "Atlantic Ocean",
            "Indian Ocean",
            "Pacific Ocean",
            "Arctic Ocean"
        ],
        "answer": 2
    },

    {
        "question": "🌍 How many continents are there?",
        "options": [
            "5",
            "6",
            "7",
            "8"
        ],
        "answer": 2
    }

]


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):

    add_user(update.effective_user)

    item = random.choice(QUIZ_DATA)

    context.user_data["quiz_answer"] = item["answer"]

    letters = ["A", "B", "C", "D"]

    buttons = []

    for i, option in enumerate(item["options"]):

        buttons.append([
            InlineKeyboardButton(
                f"{letters[i]}) {option}",
                callback_data=f"quiz_{i}"
            )
        ])

    keyboard = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        "🌍 INTERNATIONAL QUIZ\n\n"
        f"{item['question']}\n\n"
        "সঠিক উত্তরটি নির্বাচন করুন 👇",
        reply_markup=keyboard
    )


async def quiz_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if "quiz_answer" not in context.user_data:

        await query.edit_message_text(
            "⚠️ Quiz session শেষ।\n\n"
            "আবার /quiz লিখুন।"
        )

        return

    try:

        selected = int(
            query.data.split("_")[1]
        )

    except Exception:

        await query.edit_message_text(
            "❌ Quiz error। আবার /quiz দিন।"
        )

        return

    correct = context.user_data["quiz_answer"]

    if selected == correct:

        add_balance(
            update.effective_user.id,
            QUIZ_REWARD
        )

        await query.edit_message_text(
            "🎉 সঠিক উত্তর!\n\n"
            f"🎁 Reward: +{QUIZ_REWARD} Points\n"
            f"💰 Balance: "
            f"{get_balance(update.effective_user.id):.2f} Points\n\n"
            "👉 নতুন প্রশ্নের জন্য /quiz দিন।"
        )

    else:

        await query.edit_message_text(
            "❌ ভুল উত্তর!\n\n"
            "আবার চেষ্টা করতে /quiz দিন।"
        )

    context.user_data.pop(
        "quiz_answer",
        None
    )


# =========================================================
# TASKS
# =========================================================

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):

    add_user(update.effective_user)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, description, reward
        FROM tasks
        WHERE active=1
        ORDER BY id DESC
    """)

    rows = cur.fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "📋 AVAILABLE TASKS\n\n"
            "বর্তমানে কোনো Task নেই।\n\n"
            "Admin নতুন Task যোগ করলে এখানে দেখা যাবে।"
        )

        return

    text = "📋 AVAILABLE TASKS\n\n"

    for row in rows:

        text += (
            f"🆔 Task ID: {row['id']}\n"
            f"📌 {row['title']}\n"
            f"📝 {row['description']}\n"
            f"🎁 Reward: {row['reward']:.2f} Points\n"
            f"👉 Complete করতে: /done {row['id']}\n\n"
        )

    await update.message.reply_text(text)


async def done_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    if not context.args:

        await update.message.reply_text(
            "❗ ব্যবহার:\n"
            "/done TASK_ID"
        )

        return

    try:

        task_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ Task ID সঠিক নয়।"
        )

        return

    user_id = update.effective_user.id

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title
        FROM tasks
        WHERE id=? AND active=1
    """, (task_id,))

    task = cur.fetchone()

    if not task:

        conn.close()

        await update.message.reply_text(
            "❌ Task পাওয়া যায়নি।"
        )

        return

    cur.execute("""
        SELECT id
        FROM task_submissions
        WHERE user_id=? AND task_id=?
          AND status IN ('Pending', 'Approved')
    """, (
        user_id,
        task_id
    ))

    already = cur.fetchone()

    if already:

        conn.close()

        await update.message.reply_text(
            "⚠️ এই Task আপনি ইতিমধ্যে submit করেছেন।"
        )

        return

    cur.execute("""
        INSERT INTO task_submissions
        (user_id, task_id, status, created_at)
        VALUES (?, ?, 'Pending', ?)
    """, (
        user_id,
        task_id,
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ Task Submission Received!\n\n"
        f"📌 Task: {task['title']}\n"
        "⏳ Status: Pending\n\n"
        "Admin approve করলে Reward Balance-এ যোগ হবে।"
    )


# =========================================================
# GAMES
# =========================================================

async def games(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🎮 GAMES\n\n"
        "🎯 Number Guess Game\n\n"
        "১ থেকে ৫-এর মধ্যে একটি সংখ্যা guess করুন।\n"
        "ব্যবহার করুন:\n\n"
        "/guess 3\n\n"
        f"🎁 জিতলে +{GAME_REWARD} Points"
    )


async def guess(update: Update, context: ContextTypes.DEFAULT_TYPE):

    add_user(update.effective_user)

    if not context.args:

        await update.message.reply_text(
            "🎯 ১ থেকে ৫-এর মধ্যে একটি সংখ্যা দিন।\n\n"
            "উদাহরণ:\n"
            "/guess 3"
        )

        return

    try:

        number = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ শুধু ১ থেকে ৫-এর সংখ্যা দিন।"
        )

        return

    if number < 1 or number > 5:

        await update.message.reply_text(
            "❌ সংখ্যা অবশ্যই ১ থেকে ৫-এর মধ্যে হতে হবে।"
        )

        return

    winning = random.randint(1, 5)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO game_stats(user_id, wins, games)
        VALUES (?, 0, 1)
        ON CONFLICT(user_id)
        DO UPDATE SET games=games+1
    """, (
        update.effective_user.id,
    ))

    if number == winning:

        cur.execute("""
            UPDATE game_stats
            SET wins=wins+1
            WHERE user_id=?
        """, (
            update.effective_user.id,
        ))

        conn.commit()
        conn.close()

        add_balance(
            update.effective_user.id,
            GAME_REWARD
        )

        await update.message.reply_text(
            "🎉 YOU WIN!\n\n"
            f"🎯 Number: {winning}\n"
            f"🎁 Reward: +{GAME_REWARD} Points\n"
            f"💰 Balance: "
            f"{get_balance(update.effective_user.id):.2f} Points"
        )

    else:

        conn.commit()
        conn.close()

        await update.message.reply_text(
            "😔 You Lost!\n\n"
            f"🎯 Correct Number: {winning}\n\n"
            "আবার চেষ্টা করতে /games দিন।"
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

    rows = cur.fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "🏆 এখনো কোনো User নেই।"
        )

        return

    text = "🏆 TOP 10 LEADERBOARD\n\n"

    for i, row in enumerate(rows, 1):

        name = (
            row["first_name"]
            or row["username"]
            or "User"
        )

        text += (
            f"{i}. {name} — "
            f"{row['balance']:.2f} Points\n"
        )

    await update.message.reply_text(text)


# =========================================================
# WITHDRAW
# =========================================================

async def withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    balance_amount = get_balance(
        update.effective_user.id
    )

    await update.message.reply_text(
        "💸 WITHDRAWAL\n\n"
        f"💰 আপনার Balance: "
        f"{balance_amount:.2f} Points\n\n"
        f"Minimum Withdrawal: "
        f"{MIN_WITHDRAWAL} Points\n\n"
        "Request করার format:\n"
        "/withdraw AMOUNT METHOD ACCOUNT\n\n"
        "উদাহরণ:\n"
        "/withdraw 100 bKash 017XXXXXXXX"
    )


async def create_withdrawal(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    if len(context.args) < 3:

        await update.message.reply_text(
            "❗ সঠিক Format:\n\n"
            "/withdraw AMOUNT METHOD ACCOUNT\n\n"
            "উদাহরণ:\n"
            "/withdraw 100 bKash 017XXXXXXXX"
        )

        return

    try:

        amount = float(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ Amount সঠিক নয়।"
        )

        return

    method = context.args[1]
    account = " ".join(context.args[2:])

    user_id = update.effective_user.id

    if amount < MIN_WITHDRAWAL:

        await update.message.reply_text(
            f"❌ Minimum withdrawal "
            f"{MIN_WITHDRAWAL} Points।"
        )

        return

    balance_amount = get_balance(user_id)

    if balance_amount < amount:

        await update.message.reply_text(
            "❌ আপনার Balance যথেষ্ট নয়।\n\n"
            f"Balance: {balance_amount:.2f}"
        )

        return

    # টাকা কেটে Pending রাখা হবে
    if not subtract_balance(user_id, amount):

        await update.message.reply_text(
            "❌ Withdrawal তৈরি করা যায়নি।"
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO withdrawals
        (
            user_id,
            amount,
            method,
            account,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, 'Pending', ?)
    """, (
        user_id,
        amount,
        method,
        account,
        datetime.utcnow().isoformat()
    ))

    withdrawal_id = cur.lastrowid

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ WITHDRAWAL REQUEST CREATED\n\n"
        f"🆔 Request ID: {withdrawal_id}\n"
        f"💰 Amount: {amount:.2f} Points\n"
        f"💳 Method: {method}\n"
        f"📱 Account: {account}\n"
        "⏳ Status: Pending\n\n"
        "Admin review করার পর request process হবে।"
    )


# =========================================================
# MY ID
# =========================================================

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🆔 আপনার Telegram User ID:\n\n"
        f"{update.effective_user.id}"
    )


# =========================================================
# RULES
# =========================================================

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "📜 EHAN EARN BOT RULES\n\n"
        "1️⃣ Fake account ব্যবহার করা যাবে না।\n"
        "2️⃣ Multiple account abuse করা যাবে না।\n"
        "3️⃣ Referral abuse করা যাবে না।\n"
        "4️⃣ কোনো প্রতারণামূলক কাজ করা যাবে না।\n"
        "5️⃣ Task fraud করা যাবে না।\n"
        "6️⃣ Withdrawal-এর প্রয়োজনীয় শর্ত পূরণ করতে হবে।\n\n"
        "⚠️ Points-এর cash value বা withdrawal "
        "শুধু official system-এর শর্ত অনুযায়ী হবে।"
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
        "/start — Start\n"
        "/balance — Balance\n"
        "/mining — Mining\n"
        "/daily — Daily Bonus\n"
        "/quiz — Quiz\n"
        "/tasks — Tasks\n"
        "/done ID — Submit Task\n"
        "/referral — Referral\n"
        "/games — Games\n"
        "/guess 3 — Guess Game\n"
        "/leaderboard — Leaderboard\n"
        "/withdraw — Withdrawal Info\n"
        "/withdraw 100 bKash 017XXXXXXXX\n"
        "/myid — Telegram ID\n"
        "/rules — Rules\n"
        "/help — Help"
    )


# =========================================================
# ADMIN STATS
# =========================================================

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

    total_balance = (
        cur.fetchone()["total"]
        or 0
    )

    cur.execute("""
        SELECT COUNT(*) AS total
        FROM withdrawals
        WHERE status='Pending'
    """)

    pending_withdrawals = (
        cur.fetchone()["total"]
    )

    cur.execute("""
        SELECT COUNT(*) AS total
        FROM task_submissions
        WHERE status='Pending'
    """)

    pending_tasks = (
        cur.fetchone()["total"]
    )

    conn.close()

    await update.message.reply_text(
        "👨‍💻 ADMIN STATISTICS\n\n"
        f"👥 Total Users: {total_users}\n"
        f"💰 Total Points: {total_balance:.2f}\n"
        f"💸 Pending Withdrawals: "
        f"{pending_withdrawals}\n"
        f"📋 Pending Tasks: {pending_tasks}"
    )


# =========================================================
# ADMIN ADD TASK
# =========================================================

async def admin_add_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    if len(context.args) < 3:

        await update.message.reply_text(
            "❗ Format:\n\n"
            "/addtask REWARD TITLE DESCRIPTION\n\n"
            "উদাহরণ:\n"
            "/addtask 20 Facebook Follow Page"
        )

        return

    try:

        reward = float(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ Reward সঠিক নয়।"
        )

        return

    title = context.args[1]

    description = " ".join(
        context.args[2:]
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO tasks
        (title, description, reward, active)
        VALUES (?, ?, ?, 1)
    """, (
        title,
        description,
        reward
    ))

    task_id = cur.lastrowid

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ TASK CREATED\n\n"
        f"🆔 Task ID: {task_id}\n"
        f"📌 Title: {title}\n"
        f"🎁 Reward: {reward:.2f} Points"
    )


# =========================================================
# ADMIN PENDING WITHDRAWALS
# =========================================================

async def admin_pending_withdrawals(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, user_id, amount, method, account
        FROM withdrawals
        WHERE status='Pending'
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cur.fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "💸 কোনো Pending Withdrawal নেই।"
        )

        return

    text = "💸 PENDING WITHDRAWALS\n\n"

    for row in rows:

        text += (
            f"🆔 ID: {row['id']}\n"
            f"👤 User: {row['user_id']}\n"
            f"💰 Amount: {row['amount']}\n"
            f"💳 Method: {row['method']}\n"
            f"📱 Account: {row['account']}\n\n"
            f"Approve: /approve {row['id']}\n"
            f"Reject: /reject {row['id']}\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# ADMIN APPROVE WITHDRAWAL
# =========================================================

async def admin_approve(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "/approve WITHDRAWAL_ID"
        )

        return

    try:

        withdrawal_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ ID সঠিক নয়।"
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, amount, status
        FROM withdrawals
        WHERE id=?
    """, (
        withdrawal_id,
    ))

    row = cur.fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "❌ Withdrawal পাওয়া যায়নি।"
        )

        return

    if row["status"] != "Pending":

        conn.close()

        await update.message.reply_text(
            "⚠️ এই Withdrawal আর Pending নেই।"
        )

        return

    cur.execute("""
        UPDATE withdrawals
        SET status='Approved'
        WHERE id=?
    """, (
        withdrawal_id,
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ Withdrawal Approved.\n\n"
        f"ID: {withdrawal_id}\n"
        f"Amount: {row['amount']} Points"
    )


# =========================================================
# ADMIN REJECT WITHDRAWAL
# =========================================================

async def admin_reject(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "/reject WITHDRAWAL_ID"
        )

        return

    try:

        withdrawal_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ ID সঠিক নয়।"
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, amount, status
        FROM withdrawals
        WHERE id=?
    """, (
        withdrawal_id,
    ))

    row = cur.fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "❌ Withdrawal পাওয়া যায়নি।"
        )

        return

    if row["status"] != "Pending":

        conn.close()

        await update.message.reply_text(
            "⚠️ এই Withdrawal আর Pending নেই।"
        )

        return

    # Reject হলে Points ফেরত
    cur.execute("""
        UPDATE users
        SET balance = balance + ?
        WHERE user_id=?
    """, (
        row["amount"],
        row["user_id"]
    ))

    cur.execute("""
        UPDATE withdrawals
        SET status='Rejected'
        WHERE id=?
    """, (
        withdrawal_id,
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "❌ Withdrawal Rejected.\n\n"
        f"ID: {withdrawal_id}\n"
        f"{row['amount']} Points User-এর Balance-এ ফেরত দেওয়া হয়েছে।"
    )


# =========================================================
# ADMIN APPROVE TASK
# =========================================================

async def admin_approve_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "/approvetask SUBMISSION_ID"
        )

        return

    try:

        submission_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ ID সঠিক নয়।"
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            ts.user_id,
            ts.task_id,
            ts.status,
            t.reward,
            t.title
        FROM task_submissions ts
        JOIN tasks t
        ON ts.task_id=t.id
        WHERE ts.id=?
    """, (
        submission_id,
    ))

    row = cur.fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "❌ Submission পাওয়া যায়নি।"
        )

        return

    if row["status"] != "Pending":

        conn.close()

        await update.message.reply_text(
            "⚠️ এই submission আর Pending নেই।"
        )

        return

    cur.execute("""
        UPDATE users
        SET balance=balance+?
        WHERE user_id=?
    """, (
        row["reward"],
        row["user_id"]
    ))

    cur.execute("""
        UPDATE task_submissions
        SET status='Approved'
        WHERE id=?
    """, (
        submission_id,
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ TASK APPROVED\n\n"
        f"Submission: {submission_id}\n"
        f"Reward: +{row['reward']} Points"
    )


# =========================================================
# ADMIN PENDING TASKS
# =========================================================

async def admin_pending_tasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            ts.id,
            ts.user_id,
            ts.task_id,
            t.title,
            t.reward
        FROM task_submissions ts
        JOIN tasks t
        ON ts.task_id=t.id
        WHERE ts.status='Pending'
        ORDER BY ts.id DESC
    """)

    rows = cur.fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "📋 কোনো Pending Task নেই।"
        )

        return

    text = "📋 PENDING TASKS\n\n"

    for row in rows:

        text += (
            f"🆔 Submission: {row['id']}\n"
            f"👤 User: {row['user_id']}\n"
            f"📌 Task: {row['title']}\n"
            f"🎁 Reward: {row['reward']}\n"
            f"✅ Approve: /approvetask {row['id']}\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# ADMIN HELP
# =========================================================

async def admin_help(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    await update.message.reply_text(
        "👨‍💻 ADMIN COMMANDS\n\n"
        "/adminstats\n"
        "/addtask REWARD TITLE DESCRIPTION\n"
        "/pending\n"
        "/approve ID\n"
        "/reject ID\n"
        "/pendingtasks\n"
        "/approvetask ID\n\n"
        "User ID দেখতে:\n"
        "/myid"
    )


# =========================================================
# MAIN
# =========================================================

async def post_init(application):

    commands = [

        BotCommand("start", "Start Bot"),
        BotCommand("balance", "Check Balance"),
        BotCommand("mining", "Mining"),
        BotCommand("daily", "Daily Bonus"),
        BotCommand("quiz", "Quiz"),
        BotCommand("tasks", "Tasks"),
        BotCommand("referral", "Referral"),
        BotCommand("games", "Games"),
        BotCommand("leaderboard", "Leaderboard"),
        BotCommand("withdraw", "Withdrawal"),
        BotCommand("myid", "My Telegram ID"),
        BotCommand("rules", "Rules"),
        BotCommand("help", "Help"),
    ]

    await application.bot.set_my_commands(commands)


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
        .post_init(post_init)
        .build()
    )

    # User commands
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
        CommandHandler("daily", daily)
    )

    app.add_handler(
        CommandHandler("quiz", quiz)
    )

    app.add_handler(
        CommandHandler("tasks", tasks)
    )

    app.add_handler(
        CommandHandler("done", done_task)
    )

    app.add_handler(
        CommandHandler("games", games)
    )

    app.add_handler(
        CommandHandler("guess", guess)
    )

    app.add_handler(
        CommandHandler("leaderboard", leaderboard)
    )

    # Withdrawal
    app.add_handler(
        CommandHandler("withdraw", withdraw)
    )

    # Actual withdrawal request
    app.add_handler(
        CommandHandler("requestwithdraw", create_withdrawal)
    )

    app.add_handler(
        CommandHandler("myid", myid)
    )

    app.add_handler(
        CommandHandler("rules", rules)
    )

    app.add_handler(
        CommandHandler("help", help_command)
    )

    # Quiz buttons
    app.add_handler(
        CallbackQueryHandler(
            quiz_answer,
            pattern=r"^quiz_[0-3]$"
        )
    )

    # Admin
    app.add_handler(
        CommandHandler("adminstats", admin_stats)
    )

    app.add_handler(
        CommandHandler("adminhelp", admin_help)
    )

    app.add_handler(
        CommandHandler("addtask", admin_add_task)
    )
