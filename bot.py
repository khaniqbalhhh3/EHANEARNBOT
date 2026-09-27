import os
import json
import time
import hmac
import hashlib
import sqlite3
import random
import threading
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    MenuButtonWebApp,
)
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes


# ============================================================
# EHAN EARN BOT - COMPLETE ONE FILE VERSION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "EHAN1BOT"
).strip().lstrip("@")

WEBAPP_URL = os.getenv(
    "WEBAPP_URL",
    "https://ehanearnbot.onrender.com"
).strip().rstrip("/")

ADMIN_ID = int(
    os.getenv("ADMIN_ID", "0") or 0
)

PORT = int(
    os.getenv("PORT", "10000") or 10000
)

DB_FILE = os.getenv(
    "DB_FILE",
    "users.db"
)

# ----------------------------
# Settings
# ----------------------------

MIN_WITHDRAW = 100.0

MINING_RATE_DEFAULT = 0.02

MINING_CAP_SECONDS = 12 * 60 * 60

QUIZ_REWARD = 5.0

GUESS_REWARD = 10.0

REFERRER_REWARD = 10.0

NEW_USER_REF_REWARD = 5.0


# ============================================================
# QUIZ QUESTIONS
# ============================================================

QUESTIONS = [
    {
        "q": "What is the capital of Bangladesh?",
        "options": [
            "Dhaka",
            "Chattogram",
            "Rajshahi",
            "Sylhet"
        ],
        "a": 0
    },
    {
        "q": "How many days are there in a leap year?",
        "options": [
            "365",
            "366",
            "364",
            "360"
        ],
        "a": 1
    },
    {
        "q": "Which planet is known as the Red Planet?",
        "options": [
            "Earth",
            "Mars",
            "Venus",
            "Jupiter"
        ],
        "a": 1
    },
    {
        "q": "How many continents are there?",
        "options": [
            "5",
            "6",
            "7",
            "8"
        ],
        "a": 2
    },
    {
        "q": "Which language is primarily used to style web pages?",
        "options": [
            "HTML",
            "CSS",
            "SQL",
            "Python"
        ],
        "a": 1
    },
]


# ============================================================
# TIME
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_dt(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


# ============================================================
# DATABASE
# ============================================================

def db_conn():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("PRAGMA foreign_keys=ON")

    return conn


def ensure_column(
    conn,
    table,
    column,
    definition
):

    cols = {
        r[1]
        for r in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in cols:

        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():

    conn = db_conn()

    # -------------------------
    # USERS
    # -------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            balance REAL DEFAULT 0,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            last_mining TEXT,
            mining_started TEXT,
            mining_rate REAL DEFAULT 0.02,
            quiz_question INTEGER,
            quiz_answer INTEGER,
            quiz_expires TEXT,
            created_at TEXT
        )
        """
    )

    # Migration for old database

    columns = [
        ("username", "TEXT DEFAULT ''"),
        ("first_name", "TEXT DEFAULT ''"),
        ("balance", "REAL DEFAULT 0"),
        ("referred_by", "INTEGER"),
        ("referral_count", "INTEGER DEFAULT 0"),
        ("last_mining", "TEXT"),
        ("mining_started", "TEXT"),
        ("mining_rate", "REAL DEFAULT 0.02"),
        ("quiz_question", "INTEGER"),
        ("quiz_answer", "INTEGER"),
        ("quiz_expires", "TEXT"),
        ("created_at", "TEXT"),
    ]

    for column, definition in columns:

        ensure_column(
            conn,
            "users",
            column,
            definition
        )

    # -------------------------
    # TASKS
    # -------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            reward REAL NOT NULL,
            url TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
        """
    )

    # -------------------------
    # TASK SUBMISSIONS
    # -------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            UNIQUE(task_id, user_id)
        )
        """
    )

    # -------------------------
    # WITHDRAWALS
    # -------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            method TEXT NOT NULL,
            account TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
        """
    )

    conn.commit()

    conn.close()


# ============================================================
# USER
# ============================================================

def ensure_user(
    user_id,
    username="",
    first_name="",
    referrer_id=None
):

    conn = db_conn()

    row = conn.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    # Existing user

    if row:

        conn.execute(
            """
            UPDATE users
            SET username=?,
                first_name=?
            WHERE user_id=?
            """,
            (
                username or "",
                first_name or "",
                user_id
            )
        )

        conn.commit()

        conn.close()

        return False

    # New user

    conn.execute(
        """
        INSERT INTO users (
            user_id,
            username,
            first_name,
            balance,
            referred_by,
            referral_count,
            mining_started,
            mining_rate,
            created_at
        )
        VALUES (?, ?, ?, 0, ?, 0, ?, ?, ?)
        """,
        (
            user_id,
            username or "",
            first_name or "",
            referrer_id,
            now_iso(),
            MINING_RATE_DEFAULT,
            now_iso()
        )
    )

    # Referral

    if referrer_id and referrer_id != user_id:

        ref = conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE user_id=?
            """,
            (referrer_id,)
        ).fetchone()

        if ref:

            conn.execute(
                """
                UPDATE users
                SET balance=balance+?,
                    referral_count=referral_count+1
                WHERE user_id=?
                """,
                (
                    REFERRER_REWARD,
                    referrer_id
                )
            )

            conn.execute(
                """
                UPDATE users
                SET balance=balance+?
                WHERE user_id=?
                """,
                (
                    NEW_USER_REF_REWARD,
                    user_id
                )
            )

        else:

            conn.execute(
                """
                UPDATE users
                SET referred_by=NULL
                WHERE user_id=?
                """,
                (user_id,)
            )

    conn.commit()

    conn.close()

    return True


def get_user(user_id):

    conn = db_conn()

    row = conn.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    return row


# ============================================================
# MINING
# ============================================================

def mining_state(row):

    started = parse_dt(
        row["mining_started"]
    )

    if not started:

        started = datetime.now(
            timezone.utc
        )

    elapsed = max(
        0,
        int(
            (
                datetime.now(timezone.utc)
                - started
            ).total_seconds()
        )
    )

    elapsed = min(
        elapsed,
        MINING_CAP_SECONDS
    )

    rate = float(
        row["mining_rate"]
        or MINING_RATE_DEFAULT
    )

    available = elapsed * rate

    return (
        started,
        elapsed,
        rate,
        available
    )


def claim_mining(user_id):

    conn = db_conn()

    row = conn.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not row:

        conn.close()

        return 0.0, 0

    (
        started,
        elapsed,
        rate,
        reward
    ) = mining_state(row)

    conn.execute(
        """
        UPDATE users
        SET balance=balance+?,
            mining_started=?,
            last_mining=?
        WHERE user_id=?
        """,
        (
            reward,
            now_iso(),
            now_iso(),
            user_id
        )
    )

    conn.commit()

    conn.close()

    return reward, elapsed


# ============================================================
# LEADERBOARD
# ============================================================

def leaderboard(limit=10):

    conn = db_conn()

    rows = conn.execute(
        """
        SELECT
            user_id,
            username,
            first_name,
            balance,
            referral_count
        FROM users
        ORDER BY balance DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()

    conn.close()

    return rows


# ============================================================
# TELEGRAM MINI APP SECURITY
# ============================================================

def validate_init_data(init_data):

    if not BOT_TOKEN:
        return None

    if not init_data:
        return None

    try:

        pairs = parse_qsl(
            init_data,
            keep_blank_values=True
        )

        data = dict(pairs)

        received_hash = data.pop(
            "hash",
            ""
        )

        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={value}"
            for key, value
            in sorted(data.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            received_hash
        ):
            return None

        auth_date = int(
            data.get(
                "auth_date",
                "0"
            )
        )

        # 24 hour validity

        if (
            auth_date
            and
            time.time() - auth_date > 86400
        ):
            return None

        user_obj = json.loads(
            data.get(
                "user",
                "{}"
            )
        )

        if not user_obj.get("id"):
            return None

        return user_obj

    except Exception:

        return None


def api_user(init_data):

    user = validate_init_data(
        init_data
    )

    if not user:
        return None

    ensure_user(
        user["id"],
        user.get("username", ""),
        user.get("first_name", ""),
        None
    )

    return user


# ============================================================
# TASKS
# ============================================================

def get_tasks_for_user(user_id):

    conn = db_conn()

    rows = conn.execute(
        """
        SELECT
            t.id,
            t.title,
            t.reward,
            t.url,
            t.active,
            COALESCE(
                s.status,
                ''
            ) AS submission_status
        FROM tasks t
        LEFT JOIN task_submissions s
            ON t.id=s.task_id
            AND s.user_id=?
        WHERE t.active=1
        ORDER BY t.id DESC
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    return rows


def submit_task(
    user_id,
    task_id
):

    conn = db_conn()

    task = conn.execute(
        """
        SELECT *
        FROM tasks
        WHERE id=?
        AND active=1
        """,
        (task_id,)
    ).fetchone()

    if not task:

        conn.close()

        return (
            False,
            "Task not found"
        )

    try:

        conn.execute(
            """
            INSERT INTO task_submissions (
                task_id,
                user_id,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                "pending",
                now_iso()
            )
        )

        conn.commit()

        conn.close()

        return (
            True,
            "Submitted for review"
        )

    except sqlite3.IntegrityError:

        row = conn.execute(
            """
            SELECT status
            FROM task_submissions
            WHERE task_id=?
            AND user_id=?
            """,
            (
                task_id,
                user_id
            )
        ).fetchone()

        conn.close()

        return (
            False,
            f"Already submitted ({row['status'] if row else 'pending'})"
        )


# ============================================================
# MAIN BOT KEYBOARD
# ============================================================

def make_main_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🚀 OPEN EHAN EARN",
                    web_app=WebAppInfo(
                        url=WEBAPP_URL
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "💰 Balance",
                    callback_data="show_balance"
                ),
                InlineKeyboardButton(
                    "👥 Referral",
                    callback_data="show_referral"
                )
            ],
            [
                InlineKeyboardButton(
                    "⛏ Mining",
                    callback_data="show_mining"
                ),
                InlineKeyboardButton(
                    "🧠 Quiz",
                    callback_data="quiz_start"
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 Tasks",
                    callback_data="show_tasks"
                ),
                InlineKeyboardButton(
                    "🎮 Games",
                    callback_data="show_games"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏆 Leaderboard",
                    callback_data="show_leaderboard"
                ),
                InlineKeyboardButton(
                    "💸 Withdraw",
                    callback_data="show_withdraw"
                )
            ],
        ]
    )


# ============================================================
# BOT COMMANDS
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    referrer = None

    if context.args:

        arg = context.args[0]

        if arg.startswith("ref_"):

            try:

                referrer = int(
                    arg.split(
                        "_",
                        1
                    )[1]
                )

            except Exception:

                referrer = None

    is_new = ensure_user(
        user.id,
        user.username,
        user.first_name,
        referrer
    )

    text = (
        "🔥 <b>WELCOME TO EHAN EARN BOT</b>\n\n"
        f"Hello {user.first_name or 'Friend'}!\n\n"
        "⛏ Mine points\n"
        "🎯 Complete tasks\n"
        "🧠 Play quiz\n"
        "🎮 Play games\n"
        "👥 Invite friends\n"
        "💸 Request withdrawals\n\n"
        "Tap the button below to open "
        "your new professional dashboard."
    )

    if (
        is_new
        and
        referrer
        and
        referrer != user.id
    ):

        text += (
            "\n\n🎁 Referral bonus added!"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=make_main_keyboard()
    )


async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    ensure_user(
        update.effective_user.id,
        update.effective_user.username,
        update.effective_user.first_name
    )

    row = get_user(
        update.effective_user.id
    )

    await update.message.reply_text(
        "💰 <b>Your Balance</b>\n\n"
        f"⭐ {float(row['balance']):.2f} Points",
        parse_mode="HTML"
    )


async def referral(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    uid = update.effective_user.id

    ensure_user(
        uid,
        update.effective_user.username,
        update.effective_user.first_name
    )

    row = get_user(uid)

    link = (
        f"https://t.me/"
        f"{BOT_USERNAME}"
        f"?start=ref_{uid}"
    )

    await update.message.reply_text(
        "👥 <b>Referral</b>\n\n"
        f"Friends: {row['referral_count']}\n"
        f"Bonus per valid referral: "
        f"{REFERRER_REWARD:.0f} Points\n\n"
        f"🔗 {link}",
        parse_mode="HTML"
    )


async def mining(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    uid = update.effective_user.id

    ensure_user(
        uid,
        update.effective_user.username,
        update.effective_user.first_name
    )

    row = get_user(uid)

    (
        _,
        elapsed,
        rate,
        available
    ) = mining_state(row)

    await update.message.reply_text(
        "⛏ <b>Mining</b>\n\n"
        f"Rate: {rate:.2f} point/sec\n"
        f"Time: "
        f"{elapsed // 3600}h "
        f"{(elapsed % 3600) // 60}m\n"
        f"Available: ⭐ {available:.2f}\n\n"
        "Use the Mini App to claim.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🚀 Open Mining App",
                        web_app=WebAppInfo(
                            url=WEBAPP_URL
                        )
                    )
                ]
            ]
        )
    )


# ============================================================
# QUIZ
# ============================================================

async def quiz(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await send_quiz(
        update.effective_user.id,
        update.message
    )


async def send_quiz(
    user_id,
    message
):

    ensure_user(user_id)

    qid = random.randrange(
        len(QUESTIONS)
    )

    q = QUESTIONS[qid]

    expires = (
        datetime.now(timezone.utc)
        + timedelta(minutes=5)
    )

    conn = db_conn()

    conn.execute(
        """
        UPDATE users
        SET quiz_question=?,
            quiz_answer=?,
            quiz_expires=?
        WHERE user_id=?
        """,
        (
            qid,
            q["a"],
            expires.isoformat(),
            user_id
        )
    )

    conn.commit()

    conn.close()

    buttons = []

    for i, option in enumerate(
        q["options"]
    ):

        buttons.append(
            [
                InlineKeyboardButton(
                    f"{chr(65+i)}. {option}",
                    callback_data=f"quiz_{i}"
                )
            ]
        )

    await message.reply_text(
        "🧠 <b>Quiz</b>\n\n"
        f"{q['q']}\n\n"
        f"Reward: +{QUIZ_REWARD:.0f} Points",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


# ============================================================
# TASK COMMAND
# ============================================================

async def tasks_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    rows = get_tasks_for_user(
        update.effective_user.id
    )

    if not rows:

        await update.message.reply_text(
            "📋 No active tasks right now."
        )

        return

    lines = [
        "📋 <b>Tasks</b>",
        ""
    ]

    buttons = []

    for row in rows:

        lines.append(
            f"#{row['id']} • "
            f"{row['title']} • "
            f"+{float(row['reward']):.0f} Points • "
            f"{row['submission_status'] or 'Not submitted'}"
        )

        if row["url"]:

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"🔗 Open #{row['id']}",
                        url=row["url"]
                    )
                ]
            )

        if not row["submission_status"]:

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"✅ Submit #{row['id']}",
                        callback_data=f"task_{row['id']}"
                    )
                ]
            )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=(
            InlineKeyboardMarkup(buttons)
            if buttons
            else None
        )
    )


async def done_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use: /done TASK_ID"
        )

        return

    try:

        task_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "Invalid task ID."
        )

        return

    ok, msg = submit_task(
        update.effective_user.id,
        task_id
    )

    await update.message.reply_text(
        ("✅ " if ok else "ℹ️ ")
        + msg
    )


# ============================================================
# GAMES
# ============================================================

async def games(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎮 <b>Guess Game</b>\n\n"
        "Guess a number from 1 to 5.\n"
        "Correct answer = +10 Points.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        str(i),
                        callback_data=f"guess_{i}"
                    )
                    for i in range(1, 6)
                ]
            ]
        )
    )


# ============================================================
# LEADERBOARD
# ============================================================

async def leaderboard_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    rows = leaderboard(10)

    lines = [
        "🏆 <b>Leaderboard</b>",
        ""
    ]

    for i, row in enumerate(
        rows,
        1
    ):

        name = (
            row["username"]
            or row["first_name"]
            or str(row["user_id"])
        )

        lines.append(
            f"{i}. {name} — "
            f"⭐ {float(row['balance']):.2f}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML"
    )


# ============================================================
# WITHDRAW
# ============================================================

async def withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [
        [
            InlineKeyboardButton(
                "🟡 Binance",
                callback_data="wm_Binance"
            ),
            InlineKeyboardButton(
                "🟢 bKash",
                callback_data="wm_bKash"
            )
        ],
        [
            InlineKeyboardButton(
                "🔴 Nagad",
                callback_data="wm_Nagad"
            ),
            InlineKeyboardButton(
                "🔵 PayPal",
                callback_data="wm_PayPal"
            )
        ]
    ]

    await update.message.reply_text(
        "💸 <b>Withdraw</b>\n\n"
        f"Minimum: {MIN_WITHDRAW:.0f} Points\n\n"
        "Select a payment method.\n\n"
        "Then use:\n"
        "/requestwithdraw "
        "AMOUNT METHOD ACCOUNT",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


async def request_withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 3:

        await update.message.reply_text(
            "Use:\n"
            "/requestwithdraw "
            "AMOUNT METHOD ACCOUNT\n\n"
            "Example:\n"
            "/requestwithdraw "
            "100 bKash 017XXXXXXXX"
        )

        return

    try:

        amount = float(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "Invalid amount."
        )

        return

    method = context.args[1]

    account = " ".join(
        context.args[2:]
    ).strip()

    allowed = {
        "Binance",
        "bKash",
        "Nagad",
        "PayPal"
    }

    if method not in allowed:

        await update.message.reply_text(
            "Method must be Binance, "
            "bKash, Nagad or PayPal."
        )

        return

    if amount < MIN_WITHDRAW:

        await update.message.reply_text(
            f"Minimum withdrawal is "
            f"{MIN_WITHDRAW:.0f} Points."
        )

        return

    conn = db_conn()

    row = conn.execute(
        """
        SELECT balance
        FROM users
        WHERE user_id=?
        """,
        (
            update.effective_user.id,
        )
    ).fetchone()

    if (
        not row
        or
        float(row["balance"]) < amount
    ):

        conn.close()

        await update.message.reply_text(
            "Insufficient balance."
        )

        return

    conn.execute(
        """
        UPDATE users
        SET balance=balance-?
        WHERE user_id=?
        """,
        (
            amount,
            update.effective_user.id
        )
    )

    conn.execute(
        """
        INSERT INTO withdrawals (
            user_id,
            amount,
            method,
            account,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            update.effective_user.id,
            amount,
            method,
            account,
            "pending",
            now_iso()
        )
    )

    wid = conn.execute(
        "SELECT last_insert_rowid() AS id"
    ).fetchone()["id"]

    conn.commit()

    conn.close()

    await update.message.reply_text(
        "✅ Withdrawal request created.\n\n"
        f"Request ID: #{wid}\n"
        f"Amount: {amount:.2f}\n"
        f"Method: {method}\n"
        "Status: Pending"
    )


# ============================================================
# OTHER COMMANDS
# ============================================================

async def myid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        f"Your Telegram ID: "
        f"{update.effective_user.id}"
    )


async def rules(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "📜 <b>Rules</b>\n\n"
        "1. One account per person.\n"
        "2. Do not spam or abuse tasks.\n"
        "3. Withdrawals are reviewed manually.\n"
        "4. Points are virtual points until a withdrawal is approved.",
        parse_mode="HTML"
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "Use /start to open the dashboard.\n\n"
        "Commands:\n"
        "/balance\n"
        "/referral\n"
        "/mining\n"
        "/quiz\n"
        "/tasks\n"
        "/done\n"
        "/games\n"
        "/leaderboard\n"
        "/withdraw\n"
        "/requestwithdraw\n"
        "/myid\n"
        "/rules"
    )


# ============================================================
# ADMIN
# ============================================================

async def adminstats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    conn = db_conn()

    users = conn.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    balance = conn.execute(
        """
        SELECT COALESCE(
            SUM(balance),
            0
        ) b
        FROM users
        """
    ).fetchone()["b"]

    pending_wd = conn.execute(
        """
        SELECT COUNT(*) c
        FROM withdrawals
        WHERE status='pending'
        """
    ).fetchone()["c"]

    conn.close()

    await update.message.reply_text(
        "👑 Admin Stats\n\n"
        f"Users: {users}\n"
        f"Total points: {float(balance):.2f}\n"
        f"Pending withdrawals: {pending_wd}"
    )


async def addtask(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    raw = " ".join(
        context.args
    )

    parts = [
        p.strip()
        for p in raw.split("|")
    ]

    if len(parts) < 3:

        await update.message.reply_text(
            "Use:\n"
            "/addtask Title | Reward | URL"
        )

        return

    try:

        reward = float(parts[1])

    except Exception:

        await update.message.reply_text(
            "Reward must be a number."
        )

        return

    conn = db_conn()

    conn.execute(
        """
        INSERT INTO tasks (
            title,
            reward,
            url,
            active,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            parts[0],
            reward,
            parts[2],
            1,
            now_iso()
        )
    )

    conn.commit()

    conn.close()

    await update.message.reply_text(
        "✅ Task added."
    )


async def pending(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    conn = db_conn()

    rows = conn.execute(
        """
        SELECT *
        FROM withdrawals
        WHERE status='pending'
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "No pending withdrawals."
        )

        return

    lines = []

    for row in rows:

        lines.append(
            f"#{row['id']} | "
            f"User {row['user_id']} | "
            f"{row['amount']:.2f} | "
            f"{row['method']} | "
            f"{row['account']}\n"
            f"Approve: /approve {row['id']}\n"
            f"Reject: /reject {row['id']}"
        )

    await update.message.reply_text(
        "\n\n".join(lines)
    )


async def approve(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        update.effective_user.id != ADMIN_ID
        or not context.args
    ):
        return

    try:

        wid = int(
            context.args[0]
        )

    except Exception:

        return

    conn = db_conn()

    row = conn.execute(
        """
        SELECT *
        FROM withdrawals
        WHERE id=?
        AND status='pending'
        """,
        (wid,)
    ).fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "Withdrawal not found."
        )

        return

    conn.execute(
        """
        UPDATE withdrawals
        SET status='approved'
        WHERE id=?
        """,
        (wid,)
    )

    conn.commit()

    conn.close()

    await update.message.reply_text(
        f"✅ Withdrawal #{wid} approved."
    )


async def reject(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        update.effective_user.id != ADMIN_ID
        or not context.args
    ):
        return

    try:

        wid = int(
            context.args[0]
        )

    except Exception:

        return

    conn = db_conn()

    row = conn.execute(
        """
        SELECT *
        FROM withdrawals
        WHERE id=?
        AND status='pending'
        """,
        (wid,)
    ).fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "Withdrawal not found."
        )

        return

    conn.execute(
        """
        UPDATE withdrawals
        SET status='rejected'
        WHERE id=?
        """,
        (wid,)
    )

    conn.execute(
        """
        UPDATE users
        SET balance=balance+?
        WHERE user_id=?
        """,
        (
            row["amount"],
            row["user_id"]
        )
    )

    conn.commit()

    conn.close()

    await update.message.reply_text(
        f"↩️ Withdrawal #{wid} rejected "
        "and points refunded."
    )


async def pendingtasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    conn = db_conn()

    rows = conn.execute(
        """
        SELECT
            s.id,
            s.task_id,
            s.user_id,
            t.title
        FROM task_submissions s
        JOIN tasks t
            ON t.id=s.task_id
        WHERE s.status='pending'
        ORDER BY s.id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "No pending tasks."
        )

        return

    lines = []

    for row in rows:

        lines.append(
            f"#{row['id']} "
            f"Task {row['task_id']} "
            f"User {row['user_id']} "
            f"{row['title']}\n"
            f"Approve: /approvetask {row['id']}"
        )

    await update.message.reply_text(
        "\n\n".join(lines)
    )


async def approvetask(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        update.effective_user.id != ADMIN_ID
        or not context.args
    ):
        return

    try:

        sid = int(
            context.args[0]
        )

    except Exception:

        return

    conn = db_conn()

    row = conn.execute(
        """
        SELECT
            s.*,
            t.reward
        FROM task_submissions s
        JOIN tasks t
            ON t.id=s.task_id
        WHERE s.id=?
        AND s.status='pending'
        """,
        (sid,)
    ).fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "Submission not found."
        )

        return

    conn.execute(
        """
        UPDATE task_submissions
        SET status='approved'
        WHERE id=?
        """,
        (sid,)
    )

    conn.execute(
        """
        UPDATE users
        SET balance=balance+?
        WHERE user_id=?
        """,
        (
            row["reward"],
            row["user_id"]
        )
    )

    conn.commit()

    conn.close()

    await update.message.reply_text(
        "✅ Task approved.\n"
        f"+{row['reward']:.2f} points."
    )


async def adminhelp(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        "👑 Admin Commands\n\n"
        "/adminstats\n"
        "/addtask Title | Reward | URL\n"
        "/pending\n"
        "/approve ID\n"
        "/reject ID\n"
        "/pendingtasks\n"
        "/approvetask ID"
    )


# ============================================================
# CALLBACKS
# ============================================================

async def callbacks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    uid = query.from_user.id

    ensure_user(
        uid,
        query.from_user.username,
        query.from_user.first_name
    )

    data = query.data

    # Balance

    if data == "show_balance":

        row = get_user(uid)

        await query.message.reply_text(
            "💰 Balance:\n"
            f"⭐ {float(row['balance']):.2f}"
        )

    # Referral

    elif data == "show_referral":

        row = get_user(uid)

        link = (
            f"https://t.me/"
            f"{BOT_USERNAME}"
            f"?start=ref_{uid}"
        )

        await query.message.reply_text(
            "👥 Referrals: "
            f"{row['referral_count']}\n\n"
            f"🔗 {link}"
        )

    # Mining

    elif data == "show_mining":

        row = get_user(uid)

        (
            _,
            _,
            rate,
            available
        ) = mining_state(row)

        await query.message.reply_text(
            "⛏ Mining\n\n"
            f"Rate: {rate:.2f}/sec\n"
            f"Available: ⭐ {available:.2f}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🚀 Open App",
                            web_app=WebAppInfo(
                                url=WEBAPP_URL
                            )
                        )
                    ]
                ]
            )
        )

    # Quiz

    elif data == "quiz_start":

        await send_quiz(
            uid,
            query.message
        )

    # Tasks

    elif data == "show_tasks":

        rows = get_tasks_for_user(uid)

        if not rows:

            await query.message.reply_text(
                "📋 No active tasks."
            )

        else:

            text = "\n".join(
                [
                    f"#{r['id']} "
                    f"{r['title']} "
                    f"+{r['reward']}"
                    for r in rows
                ]
            )

            await query.message.reply_text(
                "📋 Tasks\n\n"
                + text
            )

    # Games

    elif data == "show_games":

        await query.message.reply_text(
            "🎮 Guess 1-5",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            str(i),
                            callback_data=f"guess_{i}"
                        )
                        for i in range(1, 6)
                    ]
                ]
            )
        )

    # Leaderboard

    elif data == "show_leaderboard":

        rows = leaderboard(10)

        text = []

        for i, row in enumerate(
            rows,
            1
        ):

            name = (
                row["username"]
                or row["first_name"]
                or str(row["user_id"])
            )

            text.append(
                f"{i}. {name} — "
                f"{float(row['balance']):.2f}"
            )

        await query.message.reply_text(
            "🏆 Leaderboard\n\n"
            + "\n".join(text)
        )

    # Withdraw

    elif data == "show_withdraw":

        await query.message.reply_text(
            f"💸 Minimum withdrawal: "
            f"{MIN_WITHDRAW:.0f} Points\n\n"
            "Use:\n"
            "/requestwithdraw "
            "AMOUNT METHOD ACCOUNT"
        )

    # Quiz answer

    elif data.startswith("quiz_"):

        try:

            choice = int(
                data.split(
                    "_",
                    1
                )[1]
            )

        except Exception:

            return

        conn = db_conn()

        row = conn.execute(
            """
            SELECT
                quiz_answer,
                quiz_expires
            FROM users
            WHERE user_id=?
            """,
            (uid,)
        ).fetchone()

        valid = (
            row
            and
            row["quiz_answer"] is not None
            and
            row["quiz_expires"]
            and
            parse_dt(
                row["quiz_expires"]
            )
            > datetime.now(timezone.utc)
        )

        if not valid:

            conn.close()

            await query.message.reply_text(
                "⏰ Quiz expired. "
                "Use /quiz again."
            )

            return

        if choice == int(
            row["quiz_answer"]
        ):

            conn.execute(
                """
                UPDATE users
                SET balance=balance+?,
                    quiz_answer=NULL,
                    quiz_expires=NULL
                WHERE user_id=?
                """,
                (
                    QUIZ_REWARD,
                    uid
                )
            )

            conn.commit()

            conn.close()

            await query.message.reply_text(
                f"✅ Correct!\n"
                f"+{QUIZ_REWARD:.0f} Points"
            )

        else:

            conn.close()

            await query.message.reply_text(
                "❌ Wrong answer.\n"
                "Try another quiz."
            )

    # Guess game

    elif data.startswith("guess_"):

        try:

            choice = int(
                data.split(
                    "_",
                    1
                )[1]
            )

        except Exception:

            return

        answer = random.randint(
            1,
            5
        )

        if choice == answer:

            conn = db_conn()

            conn.execute(
                """
                UPDATE users
                SET balance=balance+?
                WHERE user_id=?
                """,
                (
                    GUESS_REWARD,
                    uid
                )
            )

            conn.commit()

            conn.close()

            await query.message.reply_text(
                f"🎉 Correct!\n"
                f"Number was {answer}.\n"
                f"+{GUESS_REWARD:.0f} Points"
            )

        else:

            await query.message.reply_text(
                f"❌ Number was {answer}.\n"
                "Try again!"
            )

    # Task submit

    elif data.startswith("task_"):

        try:

            task_id = int(
                data.split(
                    "_",
                    1
                )[1]
            )

        except Exception:

            return

        ok, msg = submit_task(
            uid,
            task_id
        )

        await query.message.reply_text(
            ("✅ " if ok else "ℹ️ ")
            + msg
        )

    # Withdrawal method

    elif data.startswith("wm_"):

        method = data.split(
            "_",
            1
        )[1]

        await query.message.reply_text(
            f"Selected: {method}\n\n"
            f"Use:\n"
            f"/requestwithdraw "
            f"AMOUNT {method} ACCOUNT"
        )


# ============================================================
# TELEGRAM MENU BUTTON
# ============================================================

async def post_init(
    application
):

    if not WEBAPP_URL.startswith(
        "https://"
    ):

        print(
            "WARNING: WEBAPP_URL should "
            "normally use HTTPS."
        )

    try:

        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="🚀 Open App",
                web_app=WebAppInfo(
                    url=WEBAPP_URL
                )
            )
        )

        print(
            "Mini App menu button configured."
        )

    except Exception as e:

        print(
            "Menu button warning:",
            e
        )


# ============================================================
# MINI APP HTML
# ============================================================

HTML = r'''
<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta
name="viewport"
content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"
>

<title>EHAN EARN</title>

<script src="https://telegram.org/js/telegram-web-app.js?63"></script>

<style>

:root{
--bg:#05070b;
--card:#0d1119;
--card2:#121824;
--gold:#f6b73c;
--gold2:#ffdc7a;
--text:#ffffff;
--muted:#8e99a9;
--green:#35d07f;
--red:#ff5d6c;
}

*{
box-sizing:border-box;
}

html,
body{
margin:0;
padding:0;
background:var(--bg);
color:var(--text);
font-family:Arial,sans-serif;
min-height:100%;
-webkit-tap-highlight-color:transparent;
}

body{
padding-bottom:84px;
}

.intro{
position:fixed;
inset:0;
background:
radial-gradient(
circle at 50% 35%,
#39240a 0,
#090b11 38%,
#030407 100%
);
display:flex;
align-items:center;
justify-content:center;
z-index:99;
}

.intro.hide{
animation:fade .6s forwards;
}

@keyframes fade{
to{
opacity:0;
visibility:hidden;
}
}

.introCoin{
width:130px;
height:130px;
border-radius:50%;
display:flex;
align-items:center;
justify-content:center;
font-size:62px;
background:
radial-gradient(
circle at 35% 30%,
#ffeaa4,
#f3b632 48%,
#8d5200 100%
);
box-shadow:
0 0 20px #f6b73c,
0 0 80px #f6b73c55;
animation:coin 1.2s infinite alternate;
}

@keyframes coin{
to{
transform:scale(1.08) rotate(5deg);
box-shadow:
0 0 35px #f6b73c,
0 0 110px #f6b73c77;
}
}

.introText{
position:absolute;
bottom:23%;
font-weight:900;
letter-spacing:3px;
font-size:25px;
}

.wrap{
max-width:560px;
margin:auto;
padding:16px 14px;
}

.top{
display:flex;
justify-content:space-between;
align-items:center;
margin:4px 0 14px;
}

.brand{
font-weight:900;
font-size:20px;
}

.brand span{
color:var(--gold);
}

.avatar{
width:40px;
height:40px;
border-radius:50%;
display:flex;
align-items:center;
justify-content:center;
background:
linear-gradient(
135deg,
#ffd86b,
#a65c00
);
font-weight:900;
color:#1b1205;
}

.hero{
background:
linear-gradient(
145deg,
#151b27,
#090c12
);
border:1px solid #2a303b;
border-radius:25px;
padding:20px;
box-shadow:
inset 0 1px #ffffff08,
0 12px 35px #0008;
}

.label{
color:var(--muted);
font-size:12px;
text-transform:uppercase;
letter-spacing:1.4px;
}

.balance{
font-size:36px;
font-weight:900;
margin-top:5px;
}

.coinWrap{
display:flex;
justify-content:center;
padding:18px 0;
}

.coin{
width:165px;
height:165px;
border-radius:50%;
display:flex;
flex-direction:column;
align-items:center;
justify-content:center;
background:
radial-gradient(
circle at 32% 25%,
#fff0a8,
#f7bb42 43%,
#7b4800 100%
);
color:#2c1b00;
box-shadow:
0 0 0 7px #f6b73c18,
0 0 35px #f6b73c55,
0 0 100px #f6b73c20;
animation:float 2.4s ease-in-out infinite;
}

@keyframes float{
50%{
transform:translateY(-6px);
}
}

.coin b{
font-size:45px;
}

.coin small{
font-weight:900;
}

.rate{
text-align:center;
color:var(--muted);
font-size:13px;
}

.rate strong{
color:var(--gold2);
}

.claim{
width:100%;
border:0;
border-radius:16px;
padding:16px;
margin-top:15px;
background:
linear-gradient(
135deg,
#ffd45e,
#eea526
);
color:#1e1303;
font-size:17px;
font-weight:900;
box-shadow:
0 10px 25px #f6b73c22;
}

.claim:active{
transform:scale(.98);
}

.grid{
display:grid;
grid-template-columns:1fr 1fr;
gap:12px;
margin-top:14px;
}

.card{
background:var(--card);
border:1px solid #222a36;
border-radius:18px;
padding:16px;
}

.card .big{
font-size:22px;
font-weight:900;
margin-top:5px;
}

.sectionTitle{
font-size:19px;
font-weight:900;
margin:22px 2px 12px;
}

.nav{
position:fixed;
left:0;
right:0;
bottom:0;
height:76px;
background:#080b11ee;
backdrop-filter:blur(14px);
border-top:1px solid #252c37;
display:grid;
grid-template-columns:repeat(5,1fr);
z-index:50;
padding-bottom:env(safe-area-inset-bottom);
}

.nav button{
background:none;
border:0;
color:#778294;
font-size:10px;
}

.nav button.active{
color:var(--gold);
}

.nav i{
display:block;
font-style:normal;
font-size:22px;
margin-bottom:3px;
}

.screen{
display:none;
}

.screen.active{
display:block;
}

.list{
display:flex;
flex-direction:column;
gap:10px;
}

.row{
background:var(--card);
border:1px solid #232b37;
border-radius:16px;
padding:14px;
display:flex;
align-items:center;
justify-content:space-between;
gap:10px;
}

.row h3{
margin:0 0 4px;
font-size:15px;
}

.row p{
margin:0;
color:var(--muted);
font-size:12px;
}

.btn{
border:0;
border-radius:11px;
padding:10px 13px;
background:var(--gold);
color:#211504;
font-weight:900;
}

.ghost{
background:#1a212c;
color:#fff;
}

.input{
width:100%;
padding:13px;
border-radius:12px;
border:1px solid #2a3340;
background:#090d14;
color:#fff;
margin:6px 0 10px;
outline:none;
}

.methodGrid{
display:grid;
grid-template-columns:1fr 1fr;
gap:10px;
}

.method{
padding:15px;
border-radius:15px;
background:#151b25;
border:1px solid #2a3340;
color:#fff;
font-weight:900;
}

.method.sel{
border-color:var(--gold);
box-shadow:
0 0 0 1px var(--gold);
}

.notice{
padding:12px;
border-radius:12px;
background:#111824;
color:#b7c0ce;
font-size:12px;
line-height:1.5;
}

.empty{
text-align:center;
padding:35px;
color:var(--muted);
}

.modal{
position:fixed;
inset:0;
background:#0009;
display:none;
align-items:flex-end;
z-index:80;
}

.modal.show{
display:flex;
}

.sheet{
width:100%;
max-width:560px;
margin:auto auto 0;
background:#0b0f16;
border-radius:24px 24px 0 0;
padding:20px;
border-top:1px solid #303947;
}

.close{
float:right;
border:0;
background:#1a212c;
color:#fff;
border-radius:50%;
width:34px;
height:34px;
}

.toast{
position:fixed;
left:50%;
bottom:95px;
transform:translateX(-50%);
background:#161d28;
border:1px solid #303947;
padding:11px 15px;
border-radius:12px;
display:none;
z-index:100;
font-size:13px;
}

.toast.show{
display:block;
}

</style>

</head>

<body>

<div
class="intro"
id="intro"
>

<div class="introCoin">
⭐
</div>

<div class="introText">
EHAN EARN
</div>

</div>


<div class="wrap">

<div class="top">

<div class="brand">
EHAN <span>EARN</span>
</div>

<div
class="avatar"
id="avatar"
>
E
</div>

</div>


<!-- ================= MINE ================= -->

<section
id="mine"
class="screen active"
>

<div class="hero">

<div class="label">
Total balance
</div>

<div class="balance">
⭐
<span id="balance">
0.00
</span>
</div>

<div class="coinWrap">

<div class="coin">

<b>
⛏
</b>

<small id="mineCount">
0.00
</small>

</div>

</div>

<div class="rate">

Mining
<strong id="rate">
0.02
</strong>
point/sec

•

<span id="timer">
00:00:00
</span>

</div>

<button
class="claim"
onclick="claim()"
>
⚡ CLAIM MINED POINTS
</button>

</div>


<div class="grid">

<div class="card">

<div class="label">
Referrals
</div>

<div
class="big"
id="refs"
>
0
</div>

</div>


<div class="card">

<div class="label">
Mining cap
</div>

<div class="big">
12 Hours
</div>

</div>

</div>


<div class="sectionTitle">
Quick Actions
</div>


<div class="grid">

<div
class="card"
onclick="openModal('quiz')"
>
🧠 <b>Quiz</b>
<p>Earn +5</p>
</div>


<div
class="card"
onclick="openModal('game')"
>
🎮 <b>Game</b>
<p>Guess & earn</p>
</div>


<div
class="card"
onclick="show('tasks')"
>
📋 <b>Tasks</b>
<p>Complete tasks</p>
</div>


<div
class="card"
onclick="openModal('withdraw')"
>
💸 <b>Withdraw</b>
<p>Request payout</p>
</div>

</div>

</section>


<!-- ================= TASKS ================= -->

<section
id="tasks"
class="screen"
>

<div class="sectionTitle">
📋 Tasks
</div>

<div
id="taskList"
class="list"
>
</div>

</section>


<!-- ================= MINERS ================= -->

<section
id="miners"
class="screen"
>

<div class="sectionTitle">
⚡ Miners
</div>

<div class="card">

<div class="label">
Current mining machine
</div>

<div class="big">
⛏ EHAN Starter Miner
</div>

<p style="color:var(--muted)">
Rate:
<span id="minerRate">
0.02
</span>
points/sec
</p>

<div class="notice">

More miner levels can be added later with upgrades,
boosts and special events.

</div>

</div>

</section>


<!-- ================= FRIENDS ================= -->

<section
id="friends"
class="screen"
>

<div class="sectionTitle">
👥 Friends
</div>

<div class="card">

<div class="label">
Your referral link
</div>

<input
id="refLink"
class="input"
readonly
>

<button
class="btn"
onclick="copyRef()"
>
Copy Link
</button>

<p style="color:var(--muted)">
Invite friends and receive referral bonuses
for valid new users.
</p>

</div>


<div
class="card"
style="margin-top:12px"
>

<div class="label">
Your referrals
</div>

<div
class="big"
id="friendCount"
>
0
</div>

</div>

</section>


<!-- ================= PROFILE ================= -->

<section
id="profile"
class="screen"
>

<div class="sectionTitle">
👤 Profile
</div>

<div class="card">

<div class="label">
Name
</div>

<div
class="big"
id="profileName"
>
User
</div>

<p
id="profileUsername"
style="color:var(--muted)"
>
@username
</p>

</div>


<div class="grid">

<div
class="card"
onclick="openModal('leader')"
>
🏆 <b>Leaderboard</b>
</div>


<div
class="card"
onclick="openModal('withdraw')"
>
💸 <b>Withdraw</b>
</div>


<div
class="card"
onclick="openModal('quiz')"
>
🧠 <b>Quiz</b>
</div>


<div
class="card"
onclick="openModal('game')"
>
🎮 <b>Games</b>
</div>

</div>

</section>

</div>


<!-- ================= BOTTOM NAV ================= -->

<div class="nav">

<button
class="active"
onclick="show('mine',this)"
>
<i>⛏</i>
Mine
</button>

<button
onclick="show('tasks',this)"
>
<i>📋</i>
Tasks
</button>

<button
onclick="show('miners',this)"
>
<i>⚡</i>
Miners
</button>

<button
onclick="show('friends',this)"
>
<i>👥</i>
Friends
</button>

<button
onclick="show('profile',this)"
>
<i>👤</i>
Profile
</button>

</div>


<!-- ================= MODAL ================= -->

<div
class="modal"
id="modal"
>

<div class="sheet">

<button
class="close"
onclick="closeModal()"
>
×
</button>

<div id="sheetContent">
</div>

</div>

</div>


<div
class="toast"
id="toast"
>
</div>


<script>

const tg =
window.Telegram?.WebApp;

if(tg){

tg.ready();

tg.expand();

try{

tg.setHeaderColor(
'#05070b'
);

tg.setBackgroundColor(
'#05070b'
);

tg.setBottomBarColor(
'#080b11'
);

}catch(e){}

}


const initData =
tg?.initData || "";


let state = null;

let selectedMethod =
"bKash";


function esc(value){

return String(
value ?? ""
).replace(
/[&<>\\"]/g,
function(m){

return {

"&":"&amp;",
"<":"&lt;",
">":"&gt;",
"\\":"&#92;",
"\"":"&quot;"

}[m];

}
);

}


async function api(
path,
body={}
){

const response =
await fetch(
path,
{
method:"POST",
headers:{
"Content-Type":
"application/json"
},
body:JSON.stringify({
...body,
initData
})
}
);

const data =
await response.json();

if(
!response.ok
||
data.error
){

throw new Error(
data.error ||
"Request failed"
);

}

return data;

}


function toast(message){

const element =
document.getElementById(
"toast"
);

element.textContent =
message;

element.classList.add(
"show"
);

setTimeout(
function(){
element.classList.remove(
"show"
);
},
2200
);

}


function show(
id,
button
){

document
.querySelectorAll(
".screen"
)
.forEach(
function(x){
x.classList.remove(
"active"
);
}
);

document
.getElementById(id)
.classList.add(
"active"
);

document
.querySelectorAll(
".nav button"
)
.forEach(
function(x){
x.classList.remove(
"active"
);
}
);

if(button){

button.classList.add(
"active"
);

}

if(id==="tasks"){

loadTasks();

}

}


async function load(){

try{

state =
await api(
"/api/me"
);

render();

await loadTasks();

}catch(error){

toast(
error.message
);

}

}


function render(){

if(!state)
return;


document.getElementById(
"balance"
).textContent =
Number(
state.balance
).toFixed(2);


document.getElementById(
"rate"
).textContent =
Number(
state.rate
).toFixed(2);


document.getElementById(
"minerRate"
).textContent =
Number(
state.rate
).toFixed(2);


document.getElementById(
"refs"
).textContent =
state.referrals;


document.getElementById(
"friendCount"
).textContent =
state.referrals;


document.getElementById(
"avatar"
).textContent =
(
state.first_name ||
"E"
).charAt(0)
.toUpperCase();


document.getElementById(
"profileName"
).textContent =
state.first_name ||
"User";


document.getElementById(
"profileUsername"
).textContent =
state.username
?
"@" + state.username
:
"Telegram user";


document.getElementById(
"refLink"
).value =
state.ref_link;


tick();

}


function tick(){

if(!state)
return;


const start =
Number(
state.mining_started_ts ||
0
);


const cap =
43200;


const rate =
Number(
state.rate ||
0.02
);


let elapsed =
Math.max(
0,
Math.min(
cap,
Math.floor(
Date.now()/1000
-start
)
)
);


let h =
Math.floor(
elapsed/3600
);


let m =
Math.floor(
(elapsed%3600)/60
);


let s =
elapsed%60;


document.getElementById(
"timer"
).textContent =
[h,m,s]
.map(
function(v){
return String(v)
.padStart(2,"0");
}
)
.join(":");


document.getElementById(
"mineCount"
).textContent =
(
elapsed*rate
).toFixed(2);


setTimeout(
tick,
1000
);

}


async function claim(){

try{

const data =
await api(
"/api/claim"
);

state =
data;

render();

toast(
"✅ " +
Number(
data.claimed
).toFixed(2) +
" points claimed"
);

}catch(error){

toast(
error.message
);

}

}


async function loadTasks(){

try{

const data =
await api(
"/api/tasks"
);

const box =
document.getElementById(
"taskList"
);

if(
!data.tasks.length
){

box.innerHTML =
'<div class="empty">No active tasks yet.</div>';

return;

}


box.innerHTML =
data.tasks.map(
function(task){

return `
<div class="row">

<div>

<h3>
${esc(task.title)}
</h3>

<p>
Reward +${Number(task.reward).toFixed(0)}
•
${esc(task.status || "Not submitted")}
</p>

</div>

<div>

${
task.url
?
`<button
class="btn"
onclick="openTask('${encodeURIComponent(task.url)}')"
>
Open
</button>`
:
""
}

${
!task.status
?
`<button
class="btn ghost"
style="margin-left:5px"
onclick="submitTask(${task.id})"
>
Submit
</button>`
:
""
}

</div>

</div>
`;

}
).join("");

}catch(error){

toast(
error.message
);

}

}


function openTask(url){

window.open(
decodeURIComponent(url),
"_blank"
);

}


async function submitTask(id){

try{

const data =
await api(
"/api/submit_task",
{
task_id:id
}
);

toast(
data.message
);

loadTasks();

}catch(error){

toast(
error.message
);

}

}


function openModal(type){

const content =
document.getElementById(
"sheetContent"
);

let html = "";


if(type==="quiz"){

html = `
<div class="sectionTitle">
🧠 Quiz
</div>

<div
id="quizBox"
class="notice"
>
Loading question...
</div>
`;

}


if(type==="game"){

html = `
<div class="sectionTitle">
🎮 Guess Game
</div>

<p style="color:var(--muted)">
Pick a number from 1 to 5.
Correct = +10 Points.
</p>

<div class="methodGrid">

${[1,2,3,4,5]
.map(
function(n){
return `
<button
class="method"
onclick="guess(${n})"
>
${n}
</button>
`;
}
)
.join("")}

</div>
`;

}


if(type==="leader"){

html = `
<div class="sectionTitle">
🏆 Leaderboard
</div>

<div
id="leaderBox"
class="list"
>
Loading...
</div>
`;

}


if(type==="withdraw"){

html = `
<div class="sectionTitle">
💸 Withdraw
</div>

<div class="notice">
Minimum withdrawal:
100 Points.
Requests are reviewed manually.
</div>

<div
class="sectionTitle"
style="font-size:15px"
>
Payment method
</div>

<div class="methodGrid">

${[
"Binance",
"bKash",
"Nagad",
"PayPal"
]
.map(
function(method){

return `
<button
class="method ${
method===selectedMethod
?
"sel"
:
""
}"
onclick="selectMethod('${method}')"
>
${method}
</button>
`;

}
)
.join("")}

</div>

<input
id="wAmount"
class="input"
type="number"
placeholder="Amount"
>

<input
id="wAccount"
class="input"
placeholder="Account / Wallet / Email"
>

<button
class="claim"
onclick="withdrawNow()"
>
Submit Withdrawal
</button>
`;

}


content.innerHTML =
html;

document
.getElementById(
"modal"
)
.classList.add(
"show"
);


if(type==="quiz"){

loadQuiz();

}


if(type==="leader"){

loadLeader();

}

}


function selectMethod(
method
){

selectedMethod =
method;

openModal(
"withdraw"
);

}


function closeModal(){

document
.getElementById(
"modal"
)
.classList.remove(
"show"
);

}


async function loadQuiz(){

try{

const data =
await api(
"/api/quiz"
);

document.getElementById(
"quizBox"
).innerHTML = `

<b>
${esc(data.question)}
</b>

<div
class="methodGrid"
style="margin-top:12px"
>

${data.options.map(
function(option,index){

return `
<button
class="method"
onclick="answerQuiz(${index})"
>
${String.fromCharCode(65+index)}.
${esc(option)}
</button>
`;

}
).join("")}

</div>
`;

}catch(error){

toast(
error.message
);

}

}


async function answerQuiz(
answer
){

try{

const data =
await api(
"/api/quiz_answer",
{
answer
}
);

toast(
data.message
);

if(data.correct){

state.balance =
data.balance;

render();

}

loadQuiz();

}catch(error){

toast(
error.message
);

}

}


async function guess(
number
){

try{

const data =
await api(
"/api/guess",
{
guess:number
}
);

toast(
data.message
);

if(
data.balance !== undefined
){

state.balance =
data.balance;

render();

}

}catch(error){

toast(
error.message
);

}

}


async function loadLeader(){

try{

const data =
await api(
"/api/leaderboard"
);

document.getElementById(
"leaderBox"
).innerHTML =
data.rows.map(
function(row,index){

return `
<div class="row">

<div>
<b>
#${index+1}
${esc(row.name)}
</b>
</div>

<strong>
⭐
${Number(row.balance).toFixed(2)}
</strong>

</div>
`;

}
).join("");

}catch(error){

toast(
error.message
);

}

}


async function withdrawNow(){

const amount =
Number(
document.getElementById(
"wAmount"
).value
);

const account =
document.getElementById(
"wAccount"
).value
.trim();


if(
!amount
||
!account
){

toast(
"Enter amount and account"
);

return;

}


try{

const data =
await api(
"/api/withdraw",
{
amount,
method:selectedMethod,
account
}
);

state.balance =
data.balance;

render();

toast(
data.message
);

closeModal();

}catch(error){

toast(
error.message
);

}

}


function copyRef(){

if(
navigator.clipboard
){

navigator.clipboard
.writeText(
document.getElementById(
"refLink"
).value
)
.then(
function(){
toast(
"Referral link copied"
);
}
)
.catch(
function(){
toast(
"Copy failed"
);
}
);

}

}


if(
!sessionStorage.getItem(
"introSeen"
)
){

setTimeout(
function(){

document
.getElementById(
"intro"
)
.classList.add(
"hide"
);

sessionStorage.setItem(
"introSeen",
"1"
);

},
1700
);

}else{

document
.getElementById(
"intro"
)
.remove();

}


load();

</script>

</body>

</html>
'''


# ============================================================
# WEB SERVER
# ============================================================

class Handler(
    BaseHTTPRequestHandler
):

    def send_data(
        self,
        status,
        body,
        content_type
    ):

        if isinstance(
            body,
            str
        ):

            data = body.encode(
                "utf-8"
            )

        else:

            data = body

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            content_type
        )

        self.send_header(
            "Content-Length",
            str(len(data))
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.end_headers()

        self.wfile.write(
            data
        )


    def do_OPTIONS(self):

        self.send_response(
            204
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET,POST,OPTIONS"
        )

        self.end_headers()


    def do_GET(self):

        path = self.path.split(
            "?",
            1
        )[0]

        if path == "/":

            self.send_data(
                200,
                HTML,
                "text/html; charset=utf-8"
            )

            return

        if path == "/health":

            self.send_data(
                200,
                "OK",
                "text/plain; charset=utf-8"
            )

            return

        self.send_data(
            404,
            json.dumps(
                {
                    "error":
                    "Not found"
                }
            ),
            "application/json; charset=utf-8"
        )


    def do_POST(self):

        try:

            length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            raw = self.rfile.read(
                length
            )

            body = json.loads(
                raw.decode()
                or "{}"
            )

        except Exception:

            self.send_data(
                400,
                json.dumps(
                    {
                        "error":
                        "Invalid JSON"
                    }
                ),
                "application/json; charset=utf-8"
            )

            return


        try:

            user = api_user(
                body.get(
                    "initData",
                    ""
                )
            )

            if not user:

                self.send_data(
                    401,
                    json.dumps(
                        {
                            "error":
                            "Telegram authorization failed. "
                            "Open this page inside the Telegram bot."
                        }
                    ),
                    "application/json; charset=utf-8"
                )

                return


            uid = int(
                user["id"]
            )

            path = self.path.split(
                "?",
                1
            )[0]


            # ------------------------
            # ME
            # ------------------------

            if path == "/api/me":

                row = get_user(uid)

                (
                    started,
                    elapsed,
                    rate,
                    available
                ) = mining_state(row)

                result = {

                    "user_id":
                    uid,

                    "username":
                    row["username"] or "",

                    "first_name":
                    row["first_name"]
                    or
                    user.get(
                        "first_name",
                        "User"
                    ),

                    "balance":
                    float(
                        row["balance"]
                    ),

                    "referrals":
                    int(
                        row["referral_count"]
                        or 0
                    ),

                    "rate":
                    rate,

                    "available":
                    available,

                    "elapsed":
                    elapsed,

                    "mining_started_ts":
                    int(
                        started.timestamp()
                    ),

                    "ref_link":
                    f"https://t.me/"
                    f"{BOT_USERNAME}"
                    f"?start=ref_{uid}"
                }

                self.send_data(
                    200,
                    json.dumps(
                        result
                    ),
                    "application/json; charset=utf-8"
                )

                return


            # ------------------------
            # CLAIM
            # ------------------------

            if path == "/api/claim":

                claimed, _ = claim_mining(
                    uid
                )

                row = get_user(uid)

                (
                    started,
                    elapsed,
                    rate,
                    available
                ) = mining_state(row)

                result = {

                    "claimed":
                    claimed,

                    "balance":
                    float(
                        row["balance"]
                    ),

                    "referrals":
                    int(
                        row["referral_count"]
                        or 0
                    ),

                    "rate":
                    rate,

                    "available":
                    available,

                    "elapsed":
                    elapsed,

                    "mining_started_ts":
                    int(
                        started.timestamp()
                    ),

                    "first_name":
                    row["first_name"]
                    or "User",

                    "username":
                    row["username"]
                    or "",

                    "ref_link":
                    f"https://t.me/"
                    f"{BOT_USERNAME}"
                    f"?start=ref_{uid}"
                }

                self.send_data(
                    200,
                    json.dumps(
                        result
                    ),
                    "application/json; charset=utf-8"
                )

                return


            # ------------------------
            # TASKS
            # ------------------------

            if path == "/api/tasks":

                rows = get_tasks_for_user(
                    uid
                )

                tasks = []

                for row in rows:

                    tasks.append(
                        {
                            "id":
                            row["id"],

                            "title":
                            row["title"],

                            "reward":
                            float(
                                row["reward"]
                            ),

                            "url":
                            row["url"] or "",

                            "status":
                            row["submission_status"]
                            or ""
                        }
                    )

                self.send_data(
                    200,
                    json.dumps(
                        {
                            "tasks":
                            tasks
                        },
                        ensure_ascii=False
                    ),
                    "application/json; charset=utf-8"
                )

                return


            # ------------------------
            # SUBMIT TASK
            # ------------------------

            if path == "/api/submit_task":

                task_id = int(
                    body.get(
                        "task_id",
                        0
                    )
                )

                ok, message = submit_task(
                    uid,
                    task_id
                )

                result = {
                    "message":
                    message
                }

                if not ok:
                    result["error"] = message

                self.send_data(
                    200 if ok else 400,
                    json.dumps(
                        result
                    ),
                    "application/json; charset=utf-8"
                )

                return


            # ------------------------
            # QUIZ
            # ------------------------

            if path == "/api/quiz":

                qid = random.randrange(
                    len(QUESTIONS)
                )

                q = QUESTIONS[qid]

                expires = (
                    datetime.now(
                        timezone.utc
                    )
                    +
                    timedelta(
                        minutes=5
                    )
                )

                conn = db_conn()

                conn.execute(
                    """
                    UPDATE users
                    SET quiz_question=?,
                        quiz_answer=?,
                        quiz_expires=?
                    WHERE user_id=?
                    """,
                    (
                        qid,
                        q["a"],
                        expires.isoformat(),
                        uid
                    )
                )

                conn.commit()

                conn.close()

                self.send_data(
                    200,
                    json.dumps(
                        {
                            "question":
                            q["q"],

                            "options":
                            q["options"]
                        },
                        ensure_ascii=False
                    ),
                    "application/json; charset=utf-8"
                )

                return


            # ------------------------
            # QUIZ ANSWER
            # ------------------------

            if path == "/api/quiz_answer":

                answer = int(
                    body.get(
                        "answer",
                        -1
                    )
                )

                conn = db_conn()

                row = conn.execute(
                    """
                    SELECT
                        quiz_answer,
                        quiz_expires,
                        balance
                    FROM users
                    WHERE user_id=?
                    """,
                    (uid,)
                ).fetchone()

                valid = (
                    row
                    and
                    row["quiz_answer"]
                    is not None
                    and
                    row["quiz_expires"]
                    and
                    parse_dt(
                        row["quiz_expires"]
                    )
                    >
                    datetime.now(
                        timezone.utc
                    )
                )

                if not valid:

                    conn.close()

                    self.send_data(
                        400,
                        json.dumps(
                            {
                                "error":
                                "Quiz expired. "
                                "Start a new quiz."
                            }
                        ),
                        "application/json; charset=utf-8"
                    )

                    return

                if answer == int(
                    row["quiz_answer"]
                ):

                    conn.execute(
                        """
                        UPDATE users
                        SET balance=balance+?,
                            quiz_answer=NULL,
                            quiz_expires=NULL
                        WHERE user_id=?
                        """,
                        (
                            QUIZ_REWARD,
                            uid
                        )
                    )

                    conn.commit()

                    new_balance = (
                        float(
                            row["balance"]
                        )
                        +
                        QUIZ_REWARD
                    )

                    conn.close()

                    self.send_data(
                        200,
                        json.dumps(
                            {
                                "correct":
                                True,

                                "balance":
                                new_balance,

                                "message":
                                f"Correct! "
                                f"+{QUIZ_REWARD:.0f} Points"
                            }
                        ),
                        "application/json; charset=utf-8"
                    )

                    return

                conn.close()

                self.send_data(
                    200,
                    json.dumps(
                        {
                            "correct":
                            False,

                            "message":
                            "Wrong answer. "
                            "Try again."
                        }
                    ),
                    "application/json; charset=utf-8"
                )

                return


            # ------------------------
            # GUESS GAME
            # ------------------------

            if path == "/api/guess":

                guess = int(
                    body.get(
                        "guess",
                        0
                    )
                )

                answer = random.randint(
                    1,
                    5
                )

                conn = db_conn()

                row = conn.execute(
                    """
                    SELECT balance
                    FROM users
                    WHERE user_id=?
                    """,
                    (uid,)
                ).fetchone()

                if guess == answer:

                    conn.execute(
                        """
                        UPDATE users
                        SET balance=balance+?
                        WHERE user_id=?
                        """,
                        (
                            GUESS_REWARD,
                            uid
                        )
                    )

                    conn.commit()

                    balance_value = (
                        float(
                            row["balance"]
                        )
                        +
                        GUESS_REWARD
                    )

                    message = (
                        f"Correct! "
                        f"Number was {answer}. "
                        f"+{GUESS_REWARD:.0f} Points"
                    )

                else:

                    conn.commit()

                    balance_value = float(
                        row["balance"]
                    )

                    message = (
                        f"Number was {answer}. "
                        "Try again!"
                    )

                conn.close()

                self.send_data(
                    200,
                    json.dumps(
                        {
                            "balance":
                            balance_value,

                            "message":
                            message
                        }
                    ),
                    "application/json; charset=utf-8"
                )

                return


            # ------------------------
            # LEADERBOARD
            # ------------------------

            if path == "/api/leaderboard":

                rows = leaderboard(10)

                result = []

                for row in rows:

                    result.append(
                        {
                            "name":
                            row["username"]
                            or
                            row["first_name"]
                            or
                            str(
                                row["user_id"]
                            ),

                            "balance":
                            float(
                                row["balance"]
                            )
                        }
                    )

                self.send_data(
                    200,
                    json.dumps(
                        {
                            "rows":
                            result
                        },
                        ensure_ascii=False
                    ),
                    "application/json; charset=utf-8"
                )

                return


            # ------------------------
            # WITHDRAW
            # ------------------------

            if path == "/api/withdraw":

                amount = float(
                    body.get(
                        "amount",
                        0
                    )
                )

                method = str(
                    body.get(
                        "method",
                        ""
                    )
                )

                account = str(
                    body.get(
                        "account",
                        ""
                    )
                ).strip()

                allowed = {
                    "Binance",
                    "bKash",
                    "Nagad",
                    "PayPal"
                }

                if amount < MIN_WITHDRAW:

                    self.send_data(
                        400,
                        json.dumps(
                            {
                                "error":
                                f"Minimum withdrawal "
                                f"is {MIN_WITHDRAW:.0f} Points."
                            }
                        ),
                        "application/json; charset=utf-8"
                    )

                    return

                if (
                    method not in allowed
                    or
                    not account
                ):

                    self.send_data(
                        400,
                        json.dumps(
                            {
                                "error":
                                "Select a valid payment "
                                "method and enter account details."
                            }
                        ),
                        "application/json; charset=utf-8"
                    )

                    return

                conn = db_conn()

                row = conn.execute(
                    """
                    SELECT balance
                    FROM users
                    WHERE user_id=?
                    """,
                    (uid,)
                ).fetchone()

                if (
                    not row
                    or
                    float(row["balance"])
                    < amount
                ):

                    conn.close()

                    self.send_data(
                        400,
                        json.dumps(
                            {
                                "error":
                                "Insufficient balance."
                            }
                        ),
                        "application/json; charset=utf-8"
                    )

                    return

                conn.execute(
                    """
                    UPDATE users
                    SET balance=balance-?
                    WHERE user_id=?
                    """,
                    (
                        amount,
                        uid
                    )
                )

                conn.execute(
                    """
                    INSERT INTO withdrawals (
                        user_id,
                        amount,
                        method,
                        account,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uid,
                        amount,
                        method,
                        account,
                        "pending",
                        now_iso()
                    )
                )

                conn.commit()

                new_balance = (
                    float(
                        row["balance"]
                    )
                    -
                    amount
                )

                conn.close()

                self.send_data(
                    200,
                    json.dumps(
                        {
                            "balance":
                            new_balance,

                            "message":
                            "Withdrawal request "
                            "submitted for review."
                        }
                    ),
                    "application/json; charset=utf-8"
                )

                return


            # ------------------------
            # UNKNOWN API
            # ------------------------

            self.send_data(
                404,
                json.dumps(
                    {
                        "error":
                        "Unknown API"
                    }
                ),
                "application/json; charset=utf-8"
            )


        except Exception as error:

            print(
                "API ERROR:",
                repr(error)
            )

            self.send_data(
                500,
                json.dumps(
                    {
                        "error":
                        "Server error. "
                        "Please try again."
                    }
                ),
                "application/json; charset=utf-8"
            )


    def log_message(
        self,
        format,
        *args
    ):

        return


# ============================================================
# WEB SERVER START
# ============================================================

def start_server():

    server = ThreadingHTTPServer(
        (
            "0.0.0.0",
            PORT
        ),
        Handler
    )

    print(
        f"Web server running on "
        f"0.0.0.0:{PORT}"
    )

    server.serve_forever()


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN is missing. "
            "Add BOT_TOKEN in Render "
            "Environment Variables."
        )

    init_db()

    threading.Thread(
        target=start_server,
        daemon=True
    ).start()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # -------------------------
    # User Commands
    # -------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "balance",
            balance
        )
    )

    application.add_handler(
        CommandHandler(
            "referral",
            referral
        )
    )

    application.add_handler(
        CommandHandler(
            "mining",
            mining
        )
    )

    application.add_handler(
        CommandHandler(
            "quiz",
            quiz
        )
    )

    application.add_handler(
        CommandHandler(
            "tasks",
            tasks_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "done",
            done_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "games",
            games
        )
    )

    application.add_handler(
        CommandHandler(
            "leaderboard",
            leaderboard_cmd
        )
    )

    application.add_handler(
        CommandHandler(
            "withdraw",
            withdraw
        )
    )

    application.add_handler(
        CommandHandler(
            "requestwithdraw",
            request_withdraw
        )
    )

    application.add_handler(
        CommandHandler(
            "myid",
            myid
        )
    )

    application.add_handler(
        CommandHandler(
            "rules",
            rules
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    # -------------------------
    # Admin Commands
    # -------------------------

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
            "pendingwithdrawals",
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
            "approvewithdrawal",
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
            "rejectwithdrawal",
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

    # -------------------------
    # Callback Buttons
    # -------------------------

    application.add_handler(
        CallbackQueryHandler(
            callbacks
        )
    )

    print(
        "🚀 EHAN EARN BOT starting..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
