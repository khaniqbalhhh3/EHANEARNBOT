import os
import sqlite3
import random
import threading
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
    MessageHandler,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "users.db"

# =========================
# REWARDS
# =========================

MINING_REWARD = 5
MINING_COOLDOWN_HOURS = 1

REFERRAL_REWARD = 10
QUIZ_REWARD = 5
DAILY_REWARD = 10
GAME_REWARD = 10

MIN_WITHDRAWAL = 100

WITHDRAW_METHODS = {
    "binance": "Binance",
    "bkash": "bKash",
    "nagad": "Nagad",
    "paypal": "PayPal",
}


# =========================
# DATABASE
# =========================

def db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            last_mining TEXT,
            last_daily TEXT
        )
    """)

    conn.execute("""
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            reward REAL DEFAULT 0,
            active INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task_id INTEGER,
            status TEXT DEFAULT 'Pending',
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS game_stats (
            user_id INTEGER PRIMARY KEY,
            wins INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


# =========================
# USER
# =========================

def add_user(user, referral_id=None):

    conn = db()

    existing = conn.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    ).fetchone()

    if existing:

        conn.execute("""
            UPDATE users
            SET username=?,
                first_name=?
            WHERE user_id=?
        """, (
            user.username or "",
            user.first_name or "",
            user.id
        ))

    else:

        if referral_id == user.id:
            referral_id = None

        conn.execute("""
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
            referral_id
        ))

        if referral_id:

            ref_user = conn.execute(
                "SELECT user_id FROM users WHERE user_id=?",
                (referral_id,)
            ).fetchone()

            if ref_user:

                conn.execute("""
                    UPDATE users
                    SET referral_count = referral_count + 1,
                        balance = balance + ?
                    WHERE user_id=?
                """, (
                    REFERRAL_REWARD,
                    referral_id
                ))

    conn.commit()
    conn.close()


def get_balance(user_id):

    conn = db()

    row = conn.execute(
        "SELECT balance FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    if row:
        return float(row["balance"])

    return 0.0


def add_balance(user_id, amount):

    conn = db()

    conn.execute("""
        UPDATE users
        SET balance = balance + ?
        WHERE user_id=?
    """, (
        amount,
        user_id
    ))

    conn.commit()
    conn.close()


# =========================
# ADMIN
# =========================

def is_admin(user_id):

    return ADMIN_ID != 0 and user_id == ADMIN_ID


# =========================
# RENDER HEALTH SERVER
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.end_headers()

        self.wfile.write(
            b"EHAN EARN BOT is running!"
        )

    def log_message(self, *args):
        pass


def health_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    server.serve_forever()


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    referral_id = None

    if context.args:

        try:
            referral_id = int(context.args[0])
        except ValueError:
            referral_id = None

    add_user(
        update.effective_user,
        referral_id
    )

    await update.message.reply_text(
        "🎉 Welcome to EHAN EARN BOT!\n\n"
        "আপনার account তৈরি/updated হয়েছে।\n\n"

        "📌 MAIN MENU\n\n"

        "💰 /balance\n"
        "⛏️ /mining\n"
        "🎁 /daily\n"
        "🌍 /quiz\n"
        "📋 /tasks\n"
        "👥 /referral\n"
        "🎮 /games\n"
        "🏆 /leaderboard\n"
        "💸 /withdraw\n"
        "🆔 /myid\n"
        "📜 /rules\n"
        "🆘 /help"
    )


# =========================
# BALANCE
# =========================

async def balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    amount = get_balance(
        update.effective_user.id
    )

    await update.message.reply_text(
        "💰 YOUR BALANCE\n\n"
        f"💵 Balance: {amount:.2f} Points"
    )


# =========================
# REFERRAL
# =========================

async def referral(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    conn = db()

    row = conn.execute("""
        SELECT referral_count
        FROM users
        WHERE user_id=?
    """, (
        update.effective_user.id,
    )).fetchone()

    conn.close()

    count = row["referral_count"] if row else 0

    bot_username = context.bot.username

    link = (
        f"https://t.me/"
        f"{bot_username}"
        f"?start={update.effective_user.id}"
    )

    await update.message.reply_text(
        "👥 REFERRAL SYSTEM\n\n"

        f"🔗 Your Referral Link:\n"
        f"{link}\n\n"

        f"👤 Total Referrals: {count}\n"

        f"🎁 প্রতি নতুন Referral: "
        f"+{REFERRAL_REWARD} Points"
    )


# =========================
# MINING
# =========================

async def mining(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    add_user(update.effective_user)

    conn = db()

    row = conn.execute("""
        SELECT last_mining
        FROM users
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    now = datetime.utcnow()

    if row and row["last_mining"]:

        try:

            next_time = (
                datetime.fromisoformat(
                    row["last_mining"]
                )
                +
                timedelta(
                    hours=MINING_COOLDOWN_HOURS
                )
            )

            if now < next_time:

                remaining = next_time - now

                minutes = int(
                    remaining.total_seconds() / 60
                )

                conn.close()

                await update.message.reply_text(
                    "⏳ MINING COOLDOWN\n\n"
                    f"আবার Mining করতে "
                    f"{minutes} মিনিট অপেক্ষা করুন।"
                )

                return

        except Exception:
            pass

    conn.execute("""
        UPDATE users
        SET balance = balance + ?,
            last_mining = ?
        WHERE user_id=?
    """, (
        MINING_REWARD,
        now.isoformat(),
        user_id
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "⛏️ MINING SUCCESSFUL!\n\n"
        f"🎁 Reward: +{MINING_REWARD} Points\n"
        f"💰 Balance: {get_balance(user_id):.2f} Points\n\n"
        f"⏳ আবার Mining করতে "
        f"{MINING_COOLDOWN_HOURS} ঘণ্টা পরে আসুন।"
    )


# =========================
# DAILY
# =========================

async def daily(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    add_user(update.effective_user)

    today = datetime.utcnow().date().isoformat()

    conn = db()

    row = conn.execute("""
        SELECT last_daily
        FROM users
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    if row and row["last_daily"] == today:

        conn.close()

        await update.message.reply_text(
            "🎁 DAILY BONUS\n\n"
            "আপনি আজকের bonus ইতিমধ্যে নিয়েছেন।\n"
            "আগামীকাল আবার নিতে পারবেন।"
        )

        return

    conn.execute("""
        UPDATE users
        SET balance = balance + ?,
            last_daily = ?
        WHERE user_id=?
    """, (
        DAILY_REWARD,
        today,
        user_id
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🎁 DAILY BONUS RECEIVED!\n\n"
        f"+{DAILY_REWARD} Points\n\n"
        f"💰 Balance: "
        f"{get_balance(user_id):.2f} Points"
    )


# =========================
# QUIZ
# =========================

QUIZ_DATA = [

    (
        "🌍 What is the capital of Bangladesh?",
        ["Dhaka", "Chattogram", "Rajshahi", "Sylhet"],
        0
    ),

    (
        "🔴 Which planet is known as the Red Planet?",
        ["Earth", "Mars", "Jupiter", "Venus"],
        1
    ),

    (
        "📅 How many days are there in a week?",
        ["5", "6", "7", "8"],
        2
    ),

    (
        "🌊 Which is the largest ocean?",
        ["Atlantic", "Indian", "Pacific", "Arctic"],
        2
    ),

    (
        "🌍 How many continents are there?",
        ["5", "6", "7", "8"],
        2
    )

]


async def quiz(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    question, options, answer = random.choice(
        QUIZ_DATA
    )

    context.user_data["quiz_answer"] = answer

    keyboard = []

    for i, option in enumerate(options):

        keyboard.append([
            InlineKeyboardButton(
                f"{chr(65+i)}) {option}",
                callback_data=f"quiz:{i}"
            )
        ])

    await update.message.reply_text(
        "🌍 INTERNATIONAL QUIZ\n\n"
        f"{question}\n\n"
        "সঠিক উত্তর নির্বাচন করুন 👇",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
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

    selected = int(
        query.data.split(":")[1]
    )

    correct = context.user_data.pop(
        "quiz_answer"
    )

    if selected == correct:

        add_balance(
            query.from_user.id,
            QUIZ_REWARD
        )

        await query.edit_message_text(
            "🎉 সঠিক উত্তর!\n\n"
            f"🎁 Reward: +{QUIZ_REWARD} Points\n"
            f"💰 Balance: "
            f"{get_balance(query.from_user.id):.2f} Points"
        )

    else:

        await query.edit_message_text(
            "❌ ভুল উত্তর!\n\n"
            "আবার চেষ্টা করতে /quiz দিন।"
        )


# =========================
# TASKS
# =========================

async def tasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    conn = db()

    rows = conn.execute("""
        SELECT id, title, description, reward
        FROM tasks
        WHERE active=1
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "📋 AVAILABLE TASKS\n\n"
            "বর্তমানে কোনো Task নেই।"
        )

        return

    text = "📋 AVAILABLE TASKS\n\n"

    for row in rows:

        text += (
            f"🆔 Task ID: {row['id']}\n"
            f"📌 {row['title']}\n"
            f"📝 {row['description']}\n"
            f"🎁 Reward: {row['reward']:.2f} Points\n"
            f"👉 /done {row['id']}\n\n"
        )

    await update.message.reply_text(text)


async def done_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    if not context.args:

        await update.message.reply_text(
            "ব্যবহার:\n"
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

    conn = db()

    task = conn.execute("""
        SELECT *
        FROM tasks
        WHERE id=? AND active=1
    """, (
        task_id,
    )).fetchone()

    if not task:

        conn.close()

        await update.message.reply_text(
            "❌ Task পাওয়া যায়নি।"
        )

        return

    already = conn.execute("""
        SELECT id
        FROM task_submissions
        WHERE user_id=?
        AND task_id=?
        AND status IN ('Pending','Approved')
    """, (
        user_id,
        task_id
    )).fetchone()

    if already:

        conn.close()

        await update.message.reply_text(
            "⚠️ এই Task আপনি আগেই submit করেছেন।"
        )

        return

    conn.execute("""
        INSERT INTO task_submissions
        (
            user_id,
            task_id,
            status,
            created_at
        )
        VALUES (?, ?, 'Pending', ?)
    """, (
        user_id,
        task_id,
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ TASK SUBMITTED\n\n"
        f"📌 Task: {task['title']}\n"
        "⏳ Status: Pending\n\n"
        "Admin approve করলে reward যোগ হবে।"
    )


# =========================
# GAMES
# =========================

async def games(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎮 GAMES\n\n"
        "🎯 Number Guess Game\n\n"
        "১ থেকে ৫-এর মধ্যে একটি সংখ্যা guess করুন।\n\n"
        "উদাহরণ:\n"
        "/guess 3\n\n"
        f"🎁 Win করলে +{GAME_REWARD} Points"
    )


async def guess(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    if not context.args:

        await update.message.reply_text(
            "/guess 1 থেকে 5"
        )

        return

    try:

        number = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ ১ থেকে ৫-এর সংখ্যা দিন।"
        )

        return

    if number < 1 or number > 5:

        await update.message.reply_text(
            "❌ সংখ্যা ১ থেকে ৫-এর মধ্যে হতে হবে।"
        )

        return

    user_id = update.effective_user.id

    winning = random.randint(1, 5)

    conn = db()

    conn.execute("""
        INSERT INTO game_stats
        (
            user_id,
            wins,
            games
        )
        VALUES (?, 0, 1)

        ON CONFLICT(user_id)
        DO UPDATE SET games=games+1
    """, (
        user_id,
    ))

    if number == winning:

        conn.execute("""
            UPDATE game_stats
            SET wins=wins+1
            WHERE user_id=?
        """, (
            user_id,
        ))

    conn.commit()
    conn.close()

    if number == winning:

        add_balance(
            user_id,
            GAME_REWARD
        )

        await update.message.reply_text(
            "🎉 YOU WIN!\n\n"
            f"🎯 Number: {winning}\n"
            f"🎁 +{GAME_REWARD} Points\n"
            f"💰 Balance: {get_balance(user_id):.2f}"
        )

    else:

        await update.message.reply_text(
            "😔 You Lost!\n\n"
            f"🎯 Correct Number: {winning}"
        )


# =========================
# LEADERBOARD
# =========================

async def leaderboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    conn = db()

    rows = conn.execute("""
        SELECT first_name, username, balance
        FROM users
        ORDER BY balance DESC
        LIMIT 10
    """).fetchall()

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


# =========================
# WITHDRAWAL MENU
# =========================

async def withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    user_id = update.effective_user.id

    keyboard = [

        [
            InlineKeyboardButton(
                "🟡 Binance",
                callback_data="wd:Binance"
            ),

            InlineKeyboardButton(
                "🟢 bKash",
                callback_data="wd:bKash"
            )
        ],

        [
            InlineKeyboardButton(
                "🔴 Nagad",
                callback_data="wd:Nagad"
            ),

            InlineKeyboardButton(
                "🔵 PayPal",
                callback_data="wd:PayPal"
            )
        ]

    ]

    await update.message.reply_text(

        "💸 WITHDRAWAL\n\n"

        f"💰 আপনার Balance: "
        f"{get_balance(user_id):.2f} Points\n\n"

        f"🔻 Minimum Withdrawal: "
        f"{MIN_WITHDRAWAL} Points\n\n"

        "Payment Method নির্বাচন করুন 👇",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


async def withdrawal_method(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    method = query.data.split(":")[1]

    await query.message.reply_text(

        f"✅ Selected Payment Method: {method}\n\n"

        "Withdrawal request করতে লিখুন:\n\n"

        f"/requestwithdraw "
        f"{MIN_WITHDRAWAL} "
        f"{method} "
        f"YOUR_ACCOUNT\n\n"

        "উদাহরণ:\n"

        f"/requestwithdraw "
        f"100 {method} YOUR_ACCOUNT"
    )


# =========================
# CREATE WITHDRAWAL
# =========================

async def request_withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    if len(context.args) < 3:

        await update.message.reply_text(

            "❗ সঠিক Format:\n\n"

            "/requestwithdraw "
            "AMOUNT METHOD ACCOUNT\n\n"

            "Methods:\n"
            "Binance\n"
            "bKash\n"
            "Nagad\n"
            "PayPal"
        )

        return

    try:

        amount = float(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Amount সঠিক নয়।"
        )

        return

    method_input = context.args[1].lower()

    method_map = {
        "binance": "Binance",
        "bkash": "bKash",
        "nagad": "Nagad",
        "paypal": "PayPal"
    }

    if method_input not in method_map:

        await update.message.reply_text(
            "❌ Payment Method সঠিক নয়।\n\n"
            "Binance / bKash / Nagad / PayPal"
        )

        return

    method = method_map[
        method_input
    ]

    account = " ".join(
        context.args[2:]
    )

    user_id = update.effective_user.id

    if amount < MIN_WITHDRAWAL:

        await update.message.reply_text(
            f"❌ Minimum withdrawal "
            f"{MIN_WITHDRAWAL} Points।"
        )

        return

    conn = db()

    row = conn.execute("""
        SELECT balance
        FROM users
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    if not row or row["balance"] < amount:

        conn.close()

        await update.message.reply_text(
            "❌ আপনার Balance যথেষ্ট নয়।\n\n"
            f"💰 Balance: "
            f"{get_balance(user_id):.2f}"
        )

        return

    conn.execute("""
        UPDATE users
        SET balance=balance-?
        WHERE user_id=?
    """, (
        amount,
        user_id
    ))

    cursor = conn.execute("""
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

    withdrawal_id = cursor.lastrowid

    conn.commit()
    conn.close()

    await update.message.reply_text(

        "✅ WITHDRAWAL REQUEST CREATED\n\n"

        f"🆔 Request ID: {withdrawal_id}\n"
        f"💰 Amount: {amount:.2f} Points\n"
        f"💳 Method: {method}\n"
        f"📱 Account: {account}\n"
        "⏳ Status: Pending\n\n"

        "Admin review করার পর payment process হবে।"
    )


# =========================
# MY ID
# =========================

async def myid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🆔 আপনার Telegram User ID:\n\n"
        f"{update.effective_user.id}"
    )


# =========================
# RULES
# =========================

async def rules(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "📜 EHAN EARN BOT RULES\n\n"

        "1️⃣ Fake account ব্যবহার করা যাবে না।\n"
        "2️⃣ Multiple account abuse করা যাবে না।\n"
        "3️⃣ Referral abuse করা যাবে না।\n"
        "4️⃣ Task fraud করা যাবে না।\n"
        "5️⃣ Withdrawal request যাচাই করা হবে।\n\n"

        "⚠️ Points-এর cash value এবং withdrawal "
        "official system/rules অনুযায়ী হবে।"
    )


# =========================
# HELP
# =========================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "🆘 EHAN EARN BOT HELP\n\n"

        "/start\n"
        "/balance\n"
        "/mining\n"
        "/daily\n"
        "/quiz\n"
        "/tasks\n"
        "/done ID\n"
        "/referral\n"
        "/games\n"
        "/guess 3\n"
        "/leaderboard\n"
        "/withdraw\n"
        "/requestwithdraw 100 bKash 017XXXXXXXX\n"
        "/myid\n"
        "/rules\n"
        "/help"
    )


# =========================
# ADMIN STATS
# =========================

async def adminstats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    conn = db()

    users = conn.execute(
        "SELECT COUNT(*) AS total FROM users"
    ).fetchone()["total"]

    points = conn.execute(
        "SELECT COALESCE(SUM(balance),0) AS total FROM users"
    ).fetchone()["total"]

    withdrawals = conn.execute("""
        SELECT COUNT(*) AS total
        FROM withdrawals
        WHERE status='Pending'
    """).fetchone()["total"]

    tasks_count = conn.execute("""
        SELECT COUNT(*) AS total
        FROM task_submissions
        WHERE status='Pending'
    """).fetchone()["total"]

    conn.close()

    await update.message.reply_text(

        "👨‍💻 ADMIN STATISTICS\n\n"

        f"👥 Users: {users}\n"
        f"💰 Total Points: {points:.2f}\n"
        f"💸 Pending Withdrawals: {withdrawals}\n"
        f"📋 Pending Tasks: {tasks_count}"
    )


# =========================
# ADMIN ADD TASK
# =========================

async def addtask(
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
            "/addtask REWARD TITLE DESCRIPTION"
        )

        return

    try:

        reward = float(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Reward সঠিক নয়।"
        )

        return

    title = context.args[1]

    description = " ".join(
        context.args[2:]
    )

    conn = db()

    cursor = conn.execute("""
        INSERT INTO tasks
        (
            title,
            description,
            reward,
            active
        )
        VALUES (?, ?, ?, 1)
    """, (
        title,
        description,
        reward
    ))

    task_id = cursor.lastrowid

    conn.commit()
    conn.close()

    await update.message.reply_text(

        "✅ TASK CREATED\n\n"

        f"🆔 Task ID: {task_id}\n"
        f"📌 Title: {title}\n"
        f"🎁 Reward: {reward:.2f} Points"
    )


# =========================
# ADMIN PENDING WITHDRAWALS
# =========================

async def pending(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM withdrawals
        WHERE status='Pending'
        ORDER BY id DESC
        LIMIT 30
    """).fetchall()

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
            f"✅ /approve {row['id']}\n"
            f"❌ /reject {row['id']}\n\n"
        )

    await update.message.reply_text(text)


# =========================
# ADMIN APPROVE
# =========================

async def approve(
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

        withdrawal_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ ID সঠিক নয়।"
        )

        return

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM withdrawals
        WHERE id=?
    """, (
        withdrawal_id,
    )).fetchone()

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

    conn.execute("""
        UPDATE withdrawals
        SET status='Approved'
        WHERE id=?
    """, (
        withdrawal_id,
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(

        "✅ WITHDRAWAL APPROVED\n\n"

        f"🆔 ID: {withdrawal_id}\n"
        f"💰 Amount: {row['amount']} Points\n"
        f"💳 Method: {row['method']}\n"
        f"📱 Account: {row['account']}"
    )


# =========================
# ADMIN REJECT
# =========================

async def reject(
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

        withdrawal_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ ID সঠিক নয়।"
        )

        return

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM withdrawals
        WHERE id=?
    """, (
        withdrawal_id,
    )).fetchone()

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

    conn.execute("""
        UPDATE users
        SET balance=balance+?
        WHERE user_id=?
    """, (
        row["amount"],
        row["user_id"]
    ))

    conn.execute("""
        UPDATE withdrawals
        SET status='Rejected'
        WHERE id=?
    """, (
        withdrawal_id,
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(

        "❌ WITHDRAWAL REJECTED\n\n"

        f"ID: {withdrawal_id}\n"
        f"{row['amount']} Points User-এর Balance-এ ফেরত দেওয়া হয়েছে।"
    )


# =========================
# ADMIN PENDING TASKS
# =========================

async def pendingtasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user.id):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    conn = db()

    rows = conn.execute("""
        SELECT
            ts.id,
            ts.user_id,
            t.title,
            t.reward
        FROM task_submissions ts

        JOIN tasks t
        ON t.id=ts.task_id

        WHERE ts.status='Pending'

        ORDER BY ts.id DESC
    """).fetchall()

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
            f"✅ /approvetask {row['id']}\n\n"
        )

    await update.message.reply_text(text)


# =========================
# ADMIN APPROVE TASK
# =========================

async def approvetask(
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

        submission_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ ID সঠিক নয়।"
        )

        return

    conn = db()

    row = conn.execute("""
        SELECT
            ts.*,
            t.reward,
            t.title
        FROM task_submissions ts

        JOIN tasks t
        ON t.id=ts.task_id

        WHERE ts.id=?
    """, (
        submission_id,
    )).fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "❌ Submission পাওয়া যায়নি।"
        )

        return

    if row["status"] != "Pending":

        conn.close()

        await update.message.reply_text(
            "⚠️ Submission already processed."
        )

        return

    conn.execute("""
        UPDATE users
        SET balance=balance+?
        WHERE user_id=?
    """, (
        row["reward"],
        row["user_id"]
    ))

    conn.execute("""
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


# =========================
# ADMIN HELP
# =========================

async def adminhelp(
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
        "/approvetask ID"
    )


# =========================
# COMMENT REPLY
# =========================

async def comment_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    if update.message.text.startswith("/"):
        return

    bot = context.bot

    me = await bot.get_me()

    text = update.message.text.lower()

    mentioned = False

    if me.username:

        if (
            f"@{me.username.lower()}"
            in text
        ):
            mentioned = True

    replied_to_bot = False

    if update.message.reply_to_message:

        if update.message.reply_to_message.from_user:

            if (
                update.message.reply_to_message
                .from_user.id
                == me.id
            ):
                replied_to_bot = True

    if mentioned or replied_to_bot:

        await update.message.reply_text(
            "🤖 EHAN EARN BOT\n\n"
            "আপনার message পেয়েছি।\n\n"
            "সাহায্যের জন্য /help লিখুন।"
        )


# =========================
# BOT COMMAND MENU
# =========================

async def post_init(application):

    commands = [

        BotCommand(
            "start",
            "Start Bot"
        ),

        BotCommand(
            "balance",
            "Check Balance"
        ),

        BotCommand(
            "mining",
            "Mining"
        ),

        BotCommand(
            "daily",
            "Daily Bonus"
        ),

        BotCommand(
            "quiz",
            "Quiz"
        ),

        BotCommand(
            "tasks",
            "Tasks"
        ),

        BotCommand(
            "referral",
            "Referral"
        ),

        BotCommand(
            "games",
            "Games"
        ),

        BotCommand(
            "leaderboard",
            "Leaderboard"
        ),

        BotCommand(
            "withdraw",
            "Withdraw"
        ),

        BotCommand(
            "myid",
            "My Telegram ID"
        ),

        BotCommand(
            "rules",
            "Rules"
        ),

        BotCommand(
            "help",
            "Help"
        )

    ]

    await application.bot.set_my_commands(
        commands
    )


# =========================
# MAIN
# =========================

def main():

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    init_db()

    threading.Thread(
        target=health_server,
        daemon=True
    ).start()

    application = (
        Application
        .builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    # USER COMMANDS

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("balance", balance_command)
    )

    application.add_handler(
        CommandHandler("mining", mining)
    )

    application.add_handler(
        CommandHandler("daily", daily)
    )

    application.add_handler(
        CommandHandler("quiz", quiz)
    )

    application.add_handler(
        CommandHandler("tasks", tasks)
    )

    application.add_handler(
        CommandHandler("done", done_task)
    )

    application.add_handler(
        CommandHandler("referral", referral)
    )

    application.add_handler(
        CommandHandler("games", games)
    )

    application.add_handler(
        CommandHandler("guess", guess)
    )

    application.add_handler(
        CommandHandler("leaderboard", leaderboard)
    )

    application.add_handler(
        CommandHandler("withdraw", withdraw)
    )

    application.add_handler(
        CommandHandler(
            "requestwithdraw",
            request_withdraw
        )
    )

    application.add_handler(
        CommandHandler("myid", myid)
    )

    application.add_handler(
        CommandHandler("rules", rules)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    # QUIZ BUTTON

    application.add_handler(
        CallbackQueryHandler(
            quiz_answer,
            pattern=r"^quiz:[0-3]$"
        )
    )

    # WITHDRAW BUTTON

    application.add_handler(
        CallbackQueryHandler(
            withdrawal_method,
            pattern=r"^wd:(Binance|bKash|Nagad|PayPal)$"
        )
    )

    # ADMIN

    application.add_handler(
        CommandHandler(
            "adminstats",
            adminstats
        )
    )

    application.add_handler(
        CommandHandler(
            "addtask",
            addtask
        )
    )

    application.add_handler(
        CommandHandler(
            "pending",
            pending
        )
    )

    application.add_handler(
        CommandHandler(
            "approve",
            approve
        )
    )

    application.add_handler(
        CommandHandler(
            "reject",
            reject
        )
    )

    application.add_handler(
        CommandHandler(
            "pendingtasks",
            pendingtasks
        )
    )

    application.add_handler(
        CommandHandler(
            "approvetask",
            approvetask
        )
    )

    application.add_handler(
        CommandHandler(
            "adminhelp",
            adminhelp
        )
    )

    # COMMENTS / MENTIONS

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            comment_reply
        )
    )

    print(
        "🚀 EHAN EARN BOT is starting..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
