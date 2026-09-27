import os
import sqlite3
import random
import threading
import json
import time
import hmac
import hashlib
import urllib.parse

from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    WebAppInfo,
    MenuButtonWebApp,
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")

PORT = int(os.getenv("PORT", "10000"))

ADMIN_ID = int(
    os.getenv("ADMIN_ID", "0")
)

WEBAPP_URL = os.getenv(
    "WEBAPP_URL",
    "https://ehanearnbot.onrender.com"
)

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "EHAN1BOT"
)

DB_FILE = "users.db"


# ============================================================
# SETTINGS
# ============================================================

MIN_WITHDRAWAL = 100

MINING_RATE = 0.02

MINING_MAX_HOURS = 12

MINING_MAX_SECONDS = (
    MINING_MAX_HOURS * 60 * 60
)

REFERRAL_REWARD = 10

DAILY_REWARD = 10

QUIZ_REWARD = 5

GAME_REWARD = 10


WITHDRAW_METHODS = [
    "Binance",
    "bKash",
    "Nagad",
    "PayPal",
]


# ============================================================
# DATABASE
# ============================================================

def db():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def column_exists(
    conn,
    table,
    column
):

    rows = conn.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return any(
        row["name"] == column
        for row in rows
    )


def add_column_if_missing(
    conn,
    table,
    column,
    definition
):

    if not column_exists(
        conn,
        table,
        column
    ):

        conn.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN {column} {definition}"
        )


def init_db():

    conn = db()

    # USERS

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

    # Existing database migration

    add_column_if_missing(
        conn,
        "users",
        "mining_started",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "users",
        "mining_rate",
        "REAL DEFAULT 0.02"
    )

    add_column_if_missing(
        conn,
        "users",
        "quiz_answer",
        "INTEGER"
    )

    add_column_if_missing(
        conn,
        "users",
        "quiz_question",
        "TEXT"
    )

    # WITHDRAWALS

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

    # TASKS

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            reward REAL DEFAULT 0,
            active INTEGER DEFAULT 1
        )
    """)

    # TASK SUBMISSIONS

    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task_id INTEGER,
            status TEXT DEFAULT 'Pending',
            created_at TEXT
        )
    """)

    # GAME STATS

    conn.execute("""
        CREATE TABLE IF NOT EXISTS game_stats (
            user_id INTEGER PRIMARY KEY,
            wins INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0
        )
    """)

    conn.commit()

    conn.close()


# ============================================================
# USER
# ============================================================

def add_user(
    user,
    referral_id=None
):

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

        valid_referral = None

        if referral_id:

            ref = conn.execute(
                "SELECT user_id FROM users WHERE user_id=?",
                (referral_id,)
            ).fetchone()

            if ref:
                valid_referral = referral_id

        conn.execute("""
            INSERT INTO users
            (
                user_id,
                username,
                first_name,
                balance,
                referred_by,
                referral_count,
                mining_rate
            )
            VALUES (?, ?, ?, 0, ?, 0, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            valid_referral,
            MINING_RATE
        ))

        if valid_referral:

            conn.execute("""
                UPDATE users
                SET referral_count =
                    referral_count + 1,
                    balance =
                    balance + ?
                WHERE user_id=?
            """, (
                REFERRAL_REWARD,
                valid_referral
            ))

    conn.commit()

    conn.close()


def get_user(user_id):

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM users
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    conn.close()

    return row


def get_balance(user_id):

    row = get_user(user_id)

    if not row:
        return 0.0

    return float(
        row["balance"] or 0
    )


def add_balance(
    user_id,
    amount
):

    conn = db()

    conn.execute("""
        UPDATE users
        SET balance=balance+?
        WHERE user_id=?
    """, (
        amount,
        user_id
    ))

    conn.commit()

    conn.close()


# ============================================================
# MINING ENGINE
# ============================================================

def start_mining_if_needed(
    user_id
):

    conn = db()

    row = conn.execute("""
        SELECT mining_started
        FROM users
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    if row and not row["mining_started"]:

        conn.execute("""
            UPDATE users
            SET mining_started=?
            WHERE user_id=?
        """, (
            datetime.utcnow().isoformat(),
            user_id
        ))

        conn.commit()

    conn.close()


def mining_info(user_id):

    row = get_user(user_id)

    if not row:

        return {
            "active": False,
            "earned": 0,
            "rate": MINING_RATE,
            "seconds": 0
        }

    started = row["mining_started"]

    rate = float(
        row["mining_rate"]
        or MINING_RATE
    )

    if not started:

        return {
            "active": False,
            "earned": 0,
            "rate": rate,
            "seconds": 0
        }

    try:

        start_time = datetime.fromisoformat(
            started
        )

        elapsed = (
            datetime.utcnow()
            - start_time
        ).total_seconds()

        elapsed = max(
            0,
            min(
                elapsed,
                MINING_MAX_SECONDS
            )
        )

        earned = elapsed * rate

        return {
            "active": elapsed < MINING_MAX_SECONDS,
            "earned": earned,
            "rate": rate,
            "seconds": int(elapsed)
        }

    except Exception:

        return {
            "active": False,
            "earned": 0,
            "rate": rate,
            "seconds": 0
        }


def claim_mining(user_id):

    conn = db()

    row = conn.execute("""
        SELECT mining_started,
               mining_rate
        FROM users
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    if not row or not row["mining_started"]:

        if row:

            conn.execute("""
                UPDATE users
                SET mining_started=?
                WHERE user_id=?
            """, (
                datetime.utcnow().isoformat(),
                user_id
            ))

            conn.commit()

        conn.close()

        return 0

    try:

        start_time = datetime.fromisoformat(
            row["mining_started"]
        )

        elapsed = (
            datetime.utcnow()
            - start_time
        ).total_seconds()

        elapsed = max(
            0,
            min(
                elapsed,
                MINING_MAX_SECONDS
            )
        )

        rate = float(
            row["mining_rate"]
            or MINING_RATE
        )

        reward = elapsed * rate

        conn.execute("""
            UPDATE users
            SET balance=balance+?,
                mining_started=?
            WHERE user_id=?
        """, (
            reward,
            datetime.utcnow().isoformat(),
            user_id
        ))

        conn.commit()

        conn.close()

        return reward

    except Exception:

        conn.close()

        return 0


# ============================================================
# TELEGRAM MINI APP AUTH
# ============================================================

def validate_init_data(
    init_data
):

    if not init_data or not TOKEN:

        return None

    try:

        data = urllib.parse.parse_qs(
            init_data,
            strict_parsing=True
        )

        received_hash = data.get(
            "hash",
            [None]
        )[0]

        if not received_hash:

            return None

        pairs = []

        for key in sorted(data.keys()):

            if key == "hash":
                continue

            value = data[key][0]

            pairs.append(
                f"{key}={value}"
            )

        data_check_string = "\n".join(
            pairs
        )

        secret_key = hmac.new(
            b"WebAppData",
            TOKEN.encode(),
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
                ["0"]
            )[0]
        )

        if (
            auth_date
            and
            time.time() - auth_date > 86400
        ):

            return None

        user_json = data.get(
            "user",
            [None]
        )[0]

        if not user_json:

            return None

        user = json.loads(
            user_json
        )

        return user

    except Exception:

        return None


# ============================================================
# MINI APP HTML
# ============================================================

HTML = r"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,
    initial-scale=1.0,
    maximum-scale=1.0,
    user-scalable=no"
>

<title>EHAN EARN</title>

<script src="https://telegram.org/js/telegram-web-app.js?63"></script>

<style>

:root {
    --bg: #07110d;
    --card: #0e1d17;
    --card2: #12271e;
    --gold: #ffd21f;
    --gold2: #ff9d00;
    --green: #18e27a;
    --text: #ffffff;
    --muted: #8fa99c;
    --danger: #ff4f61;
}

* {
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
}

html,
body {

    margin: 0;
    padding: 0;

    width: 100%;
    min-height: 100%;

    background:
        radial-gradient(
            circle at 50% 20%,
            #173f2c 0,
            #07110d 48%,
            #030805 100%
        );

    color: var(--text);

    font-family:
        Arial,
        Helvetica,
        sans-serif;

}

body {

    overflow-x: hidden;

    padding-bottom:
        calc(
            88px +
            env(safe-area-inset-bottom)
        );

}

button {

    border: 0;
    outline: 0;

    font-family: inherit;

}

#intro {

    position: fixed;

    inset: 0;

    z-index: 9999;

    display: flex;

    align-items: center;

    justify-content: center;

    flex-direction: column;

    background:
        radial-gradient(
            circle,
            #174b32,
            #020604 75%
        );

    animation:
        introOut .7s ease 2.1s forwards;

}

.logoCoin {

    width: 145px;
    height: 145px;

    border-radius: 50%;

    display: flex;

    align-items: center;
    justify-content: center;

    font-size: 55px;

    font-weight: 900;

    color: #fff8c7;

    background:
        radial-gradient(
            circle at 35% 25%,
            #fff38c,
            #ffc400 35%,
            #c77800 72%,
            #6c3900 100%
        );

    border:
        7px solid #ffdf35;

    box-shadow:
        0 0 25px #ffc400,
        0 0 75px #ff9d00;

    animation:
        coinPulse 1.2s ease-in-out infinite;

}

.introTitle {

    margin-top: 25px;

    font-size: 30px;

    font-weight: 900;

    letter-spacing: 4px;

}

.introSub {

    margin-top: 8px;

    color: #9cffc8;

    font-size: 14px;

}

@keyframes coinPulse {

    0%,100% {
        transform:
            scale(1)
            rotateY(0deg);
    }

    50% {
        transform:
            scale(1.08)
            rotateY(180deg);
    }

}

@keyframes introOut {

    to {
        opacity: 0;
        visibility: hidden;
    }

}

#app {

    width: 100%;

    max-width: 520px;

    margin: 0 auto;

    padding: 18px 15px 20px;

}

.top {

    display: flex;

    align-items: center;

    justify-content: space-between;

    margin-bottom: 18px;

}

.profileMini {

    display: flex;

    align-items: center;

    gap: 10px;

}

.avatar {

    width: 45px;
    height: 45px;

    border-radius: 50%;

    display: flex;

    align-items: center;
    justify-content: center;

    background:
        linear-gradient(
            135deg,
            #ffd21f,
            #ff7b00
        );

    color: #201500;

    font-weight: 900;

    font-size: 18px;

}

.name {

    font-size: 16px;

    font-weight: 800;

}

.uid {

    font-size: 11px;

    color: var(--muted);

    margin-top: 3px;

}

.balanceBox {

    text-align: right;

}

.balanceLabel {

    font-size: 10px;

    color: var(--muted);

}

.balance {

    color: var(--gold);

    font-size: 20px;

    font-weight: 900;

}

.card {

    background:
        linear-gradient(
            145deg,
            rgba(26,55,42,.98),
            rgba(8,22,16,.98)
        );

    border:
        1px solid rgba(
            255,
            210,
            31,
            .14
        );

    border-radius: 22px;

    box-shadow:
        0 15px 50px
        rgba(0,0,0,.30);

}

.miningCard {

    padding: 20px;

    text-align: center;

    position: relative;

    overflow: hidden;

}

.miningCard::before {

    content: "";

    position: absolute;

    width: 220px;
    height: 220px;

    border-radius: 50%;

    background:
        rgba(255,210,31,.07);

    filter: blur(5px);

    left: 50%;
    top: 50%;

    transform:
        translate(-50%,-50%);

}

.status {

    position: relative;

    display: inline-flex;

    align-items: center;

    gap: 7px;

    color: #7fffc0;

    font-size: 12px;

    font-weight: 800;

}

.dot {

    width: 8px;
    height: 8px;

    background: var(--green);

    border-radius: 50%;

    box-shadow:
        0 0 12px var(--green);

}

.mineOrb {

    position: relative;

    width: 190px;
    height: 190px;

    margin: 18px auto;

    border-radius: 50%;

    display: flex;

    align-items: center;
    justify-content: center;

    background:
        radial-gradient(
            circle at 35% 25%,
            #fff7a2,
            #ffd21f 30%,
            #ff9800 62%,
            #653900 100%
        );

    border:
        7px solid #ffd83c;

    box-shadow:
        0 0 30px
        rgba(255,190,0,.55),

        inset
        0 0 25px
        rgba(255,255,255,.35);

    animation:
        floatCoin 2.6s
        ease-in-out infinite;

}

.mineOrb span {

    font-size: 55px;

    filter:
        drop-shadow(
            0 5px 4px
            rgba(0,0,0,.35)
        );

}

@keyframes floatCoin {

    0%,100% {
        transform:
            translateY(0)
            rotate(-2deg);
    }

    50% {
        transform:
            translateY(-7px)
            rotate(2deg);
    }

}

.earned {

    position: relative;

    font-size: 31px;

    font-weight: 900;

    color: #fff;

    letter-spacing: .5px;

}

.rate {

    position: relative;

    margin-top: 5px;

    color: var(--muted);

    font-size: 12px;

}

.claim {

    position: relative;

    width: 100%;

    margin-top: 18px;

    padding: 17px;

    border-radius: 16px;

    color: #261900;

    font-size: 17px;

    font-weight: 900;

    background:
        linear-gradient(
            135deg,
            #ffe85c,
            #ff9d00
        );

    box-shadow:
        0 8px 25px
        rgba(255,160,0,.25);

    cursor: pointer;

}

.claim:active {

    transform: scale(.98);

}

.section {

    margin-top: 16px;

}

.sectionTitle {

    font-size: 17px;

    font-weight: 900;

    margin-bottom: 10px;

}

.grid {

    display: grid;

    grid-template-columns:
        repeat(2,1fr);

    gap: 10px;

}

.action {

    padding: 16px 12px;

    border-radius: 17px;

    background:
        rgba(16,39,29,.95);

    border:
        1px solid
        rgba(255,255,255,.05);

    color: white;

    text-align: left;

    cursor: pointer;

}

.action .icon {

    font-size: 25px;

}

.action b {

    display: block;

    margin-top: 7px;

}

.action small {

    display: block;

    margin-top: 3px;

    color: var(--muted);

}

.page {

    display: none;

}

.page.active {

    display: block;

}

.task {

    padding: 15px;

    margin-bottom: 10px;

    border-radius: 17px;

    background:
        rgba(16,39,29,.95);

}

.taskTitle {

    font-weight: 900;

}

.taskDesc {

    margin-top: 6px;

    color: var(--muted);

    font-size: 12px;

    line-height: 1.5;

}

.taskBottom {

    display: flex;

    justify-content: space-between;

    align-items: center;

    margin-top: 13px;

}

.reward {

    color: var(--gold);

    font-weight: 900;

}

.smallBtn {

    padding: 9px 14px;

    border-radius: 11px;

    background: var(--green);

    color: #062312;

    font-weight: 900;

}

.refBox {

    padding: 18px;

    border-radius: 18px;

    background:
        linear-gradient(
            135deg,
            #123d28,
            #0a1a12
        );

}

.refLink {

    margin-top: 10px;

    padding: 12px;

    border-radius: 12px;

    background: rgba(0,0,0,.3);

    color: #bfffd8;

    font-size: 11px;

    word-break: break-all;

}

.withdrawRow {

    display: flex;

    align-items: center;

    gap: 10px;

    padding: 14px;

    margin-bottom: 9px;

    border-radius: 15px;

    background:
        rgba(16,39,29,.95);

    cursor: pointer;

}

.withdrawIcon {

    width: 42px;
    height: 42px;

    border-radius: 50%;

    display: flex;

    align-items: center;
    justify-content: center;

    font-size: 20px;

    background:
        rgba(255,255,255,.1);

}

.profileRow {

    padding: 14px 0;

    border-bottom:
        1px solid
        rgba(255,255,255,.06);

    display: flex;

    justify-content: space-between;

}

.profileRow span {

    color: var(--muted);

}

.bottom {

    position: fixed;

    left: 0;
    right: 0;
    bottom: 0;

    z-index: 1000;

    padding:
        8px 10px
        calc(
            8px +
            env(safe-area-inset-bottom)
        );

    background:
        rgba(3,10,7,.96);

    backdrop-filter:
        blur(18px);

    border-top:
        1px solid
        rgba(255,255,255,.06);

}

.bottomInner {

    max-width: 520px;

    margin: 0 auto;

    display: grid;

    grid-template-columns:
        repeat(5,1fr);

}

.nav {

    padding: 6px 2px;

    text-align: center;

    color: #6e897c;

    cursor: pointer;

    font-size: 10px;

    font-weight: 700;

}

.navIcon {

    display: block;

    font-size: 22px;

    margin-bottom: 3px;

}

.nav.active {

    color: var(--gold);

}

.modal {

    position: fixed;

    inset: 0;

    z-index: 5000;

    display: none;

    align-items: flex-end;

    background:
        rgba(0,0,0,.65);

}

.modal.show {

    display: flex;

}

.sheet {

    width: 100%;

    max-width: 520px;

    margin: 0 auto;

    padding: 20px;

    border-radius:
        25px 25px 0 0;

    background:
        #0b1912;

    max-height: 85vh;

    overflow-y: auto;

}

.sheetTitle {

    font-size: 20px;

    font-weight: 900;

    margin-bottom: 16px;

}

.input {

    width: 100%;

    padding: 14px;

    margin: 7px 0;

    border: 0;

    border-radius: 13px;

    background: #15281f;

    color: white;

    outline: none;

}

.primary {

    width: 100%;

    padding: 14px;

    margin-top: 10px;

    border-radius: 13px;

    background:
        linear-gradient(
            135deg,
            #ffe85c,
            #ff9d00
        );

    color: #211700;

    font-weight: 900;

}

.closeBtn {

    width: 100%;

    padding: 12px;

    margin-top: 8px;

    border-radius: 13px;

    background: #17251e;

    color: white;

}

.toast {

    position: fixed;

    z-index: 9000;

    left: 50%;

    bottom: 100px;

    transform:
        translateX(-50%)
        translateY(20px);

    padding: 12px 17px;

    border-radius: 14px;

    background: #16261e;

    border:
        1px solid
        rgba(255,255,255,.08);

    opacity: 0;

    pointer-events: none;

    transition: .25s;

    font-size: 13px;

}

.toast.show {

    opacity: 1;

    transform:
        translateX(-50%)
        translateY(0);

}

.loading {

    text-align: center;

    padding: 30px;

    color: var(--muted);

}

</style>

</head>


<body>


<!-- INTRO -->

<div id="intro">

    <div class="logoCoin">
        EH
    </div>

    <div class="introTitle">
        EHAN EARN
    </div>

    <div class="introSub">
        START MINING • EARN POINTS
    </div>

</div>


<!-- APP -->

<div id="app">


    <!-- TOP -->

    <div class="top">

        <div class="profileMini">

            <div
                class="avatar"
                id="avatar"
            >
                E
            </div>

            <div>

                <div
                    class="name"
                    id="userName"
                >
                    EHAN USER
                </div>

                <div
                    class="uid"
                    id="userId"
                >
                    Telegram User
                </div>

            </div>

        </div>


        <div class="balanceBox">

            <div class="balanceLabel">
                TOTAL BALANCE
            </div>

            <div
                class="balance"
                id="balance"
            >
                0.00
            </div>

        </div>

    </div>


    <!-- MINE PAGE -->

    <div
        id="page-mine"
        class="page active"
    >

        <div class="card miningCard">

            <div class="status">

                <span class="dot"></span>

                <span id="miningStatus">
                    MINING ACTIVE
                </span>

            </div>


            <div class="mineOrb">

                <span>
                    ⛏️
                </span>

            </div>


            <div
                class="earned"
                id="earned"
            >
                +0.0000
            </div>


            <div class="rate">

                Mining Rate:
                <b id="rate">
                    0.0200
                </b>
                Points/sec

            </div>


            <button
                class="claim"
                onclick="claimMining()"
            >
                ⚡ CLAIM
            </button>

        </div>


        <div class="section">

            <div class="sectionTitle">
                Quick Actions
            </div>

            <div class="grid">

                <button
                    class="action"
                    onclick="openMore('daily')"
                >

                    <div class="icon">
                        🎁
                    </div>

                    <b>
                        Daily Bonus
                    </b>

                    <small>
                        Claim daily reward
                    </small>

                </button>


                <button
                    class="action"
                    onclick="openPage('tasks')"
                >

                    <div class="icon">
                        📋
                    </div>

                    <b>
                        Tasks
                    </b>

                    <small>
                        Complete & earn
                    </small>

                </button>


                <button
                    class="action"
                    onclick="openPage('friends')"
                >

                    <div class="icon">
                        👥
                    </div>

                    <b>
                        Friends
                    </b>

                    <small>
                        Invite & earn
                    </small>

                </button>


                <button
                    class="action"
                    onclick="openMore('withdraw')"
                >

                    <div class="icon">
                        💸
                    </div>

                    <b>
                        Withdraw
                    </b>

                    <small>
                        Binance / bKash
                    </small>

                </button>

            </div>

        </div>

    </div>


    <!-- TASKS -->

    <div
        id="page-tasks"
        class="page"
    >

        <div class="sectionTitle">
            📋 Available Tasks
        </div>

        <div id="taskList">
            <div class="loading">
                Loading tasks...
            </div>
        </div>

    </div>


    <!-- MINERS -->

    <div
        id="page-miners"
        class="page"
    >

        <div class="sectionTitle">
            ⚡ Miners
        </div>


        <div class="card">

            <div
                style="
                    padding:20px;
                    text-align:center;
                "
            >

                <div
                    style="
                        font-size:55px;
                    "
                >
                    ⚡
                </div>

                <h2>
                    EHAN MINER
                </h2>

                <p
                    style="
                        color:#8fa99c;
                        font-size:13px;
                    "
                >
                    Your virtual mining engine
                    is active while you are earning.
                </p>

                <div
                    style="
                        margin-top:20px;
                        color:#ffd21f;
                        font-size:25px;
                        font-weight:900;
                    "
                    id="minerRate"
                >
                    0.0200 P/s
                </div>

            </div>

        </div>


        <div class="section">

            <div class="card">

                <div
                    style="
                        padding:18px;
                    "
                >

                    <b>
                        🚀 Future Mining Boosts
                    </b>

                    <p
                        style="
                            color:#8fa99c;
                            font-size:12px;
                            line-height:1.5;
                        "
                    >
                        এখানে ভবিষ্যতে verified
                        mining boosts এবং premium
                        features যোগ করা যাবে।
                    </p>

                </div>

            </div>

        </div>

    </div>


    <!-- FRIENDS -->

    <div
        id="page-friends"
        class="page"
    >

        <div class="sectionTitle">
            👥 Friends & Referral
        </div>


        <div class="refBox">

            <div
                style="
                    font-size:28px;
                "
            >
                👥
            </div>

            <h3>
                Invite Friends
            </h3>

            <p
                style="
                    color:#8fa99c;
                    font-size:12px;
                "
            >
                আপনার referral link share করুন।
                নতুন user join করলে reward পাবেন।
            </p>


            <div
                class="refLink"
                id="refLink"
            >
                Loading...
            </div>


            <button
                class="primary"
                onclick="copyReferral()"
            >
                🔗 COPY REFERRAL LINK
            </button>

        </div>


        <div class="section">

            <div class="card">

                <div
                    style="
                        padding:20px;
                        text-align:center;
                    "
                >

                    <div
                        style="
                            color:#ffd21f;
                            font-size:35px;
                            font-weight:900;
                        "
                        id="refCount"
                    >
                        0
                    </div>

                    <div
                        style="
                            color:#8fa99c;
                            font-size:12px;
                        "
                    >
                        Total Friends
                    </div>

                </div>

            </div>

        </div>

    </div>


    <!-- PROFILE -->

    <div
        id="page-profile"
        class="page"
    >

        <div class="sectionTitle">
            👤 Profile
        </div>


        <div class="card">

            <div
                style="
                    padding:20px;
                "
            >

                <div class="profileRow">

                    <span>
                        Name
                    </span>

                    <b id="profileName">
                        -
                    </b>

                </div>


                <div class="profileRow">

                    <span>
                        Telegram ID
                    </span>

                    <b id="profileId">
                        -
                    </b>

                </div>


                <div class="profileRow">

                    <span>
                        Username
                    </span>

                    <b id="profileUsername">
                        -
                    </b>

                </div>


                <div class="profileRow">

                    <span>
                        Balance
                    </span>

                    <b
                        id="profileBalance"
                        style="
                            color:#ffd21f;
                        "
                    >
                        0.00
                    </b>

                </div>


                <div class="profileRow">

                    <span>
                        Referrals
                    </span>

                    <b id="profileRefs">
                        0
                    </b>

                </div>

            </div>

        </div>


        <div class="section">

            <button
                class="action"
                style="
                    width:100%;
                "
                onclick="openMore('more')"
            >

                ⚙️ More Features

            </button>

        </div>

    </div>

</div>


<!-- BOTTOM NAV -->

<div class="bottom">

    <div class="bottomInner">


        <div
            class="nav active"
            data-page="mine"
            onclick="openPage('mine')"
        >

            <span class="navIcon">
                ⛏️
            </span>

            Mine

        </div>


        <div
            class="nav"
            data-page="tasks"
            onclick="openPage('tasks')"
        >

            <span class="navIcon">
                📋
            </span>

            Tasks

        </div>


        <div
            class="nav"
            data-page="miners"
            onclick="openPage('miners')"
        >

            <span class="navIcon">
                ⚡
            </span>

            Miners

        </div>


        <div
            class="nav"
            data-page="friends"
            onclick="openPage('friends')"
        >

            <span class="navIcon">
                👥
            </span>

            Friends

        </div>


        <div
            class="nav"
            data-page="profile"
            onclick="openPage('profile')"
        >

            <span class="navIcon">
                👤
            </span>

            Profile

        </div>


    </div>

</div>


<!-- MODAL -->

<div
    class="modal"
    id="modal"
    onclick="closeModal(event)"
>

    <div
        class="sheet"
        id="sheet"
        onclick="event.stopPropagation()"
    >

        <div
            class="sheetTitle"
            id="sheetTitle"
        >
            EHAN EARN
        </div>

        <div id="sheetBody"></div>

        <button
            class="closeBtn"
            onclick="closeModal()"
        >
            Close
        </button>

    </div>

</div>


<div
    class="toast"
    id="toast"
>
    Done
</div>


<script>


const tg =
    window.Telegram &&
    window.Telegram.WebApp
        ? window.Telegram.WebApp
        : null;


if (tg) {

    tg.ready();

    tg.expand();

    try {
        tg.setHeaderColor("#07110d");
        tg.setBackgroundColor("#07110d");
        tg.setBottomBarColor("#030805");
    } catch(e) {}

}


const initData =
    tg
        ? tg.initData
        : "";


let state = null;

let miningTimer = null;

let referralLink = "";


async function api(
    endpoint,
    data = {}
) {

    const response =
        await fetch(
            endpoint,
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    initData:
                        initData,

                    ...data
                })
            }
        );

    const result =
        await response.json();

    if (!response.ok) {

        throw new Error(
            result.error ||
            "Request failed"
        );

    }

    return result;

}


function toast(message) {

    const el =
        document.getElementById(
            "toast"
        );

    el.innerText = message;

    el.classList.add("show");

    setTimeout(
        () => {
            el.classList.remove("show");
        },
        2200
    );

}


async function loadMe() {

    try {

        const data =
            await api(
                "/api/me"
            );

        state = data;

        renderUser();

        startMiningClock();

        loadTasks();

    } catch(error) {

        toast(
            "Mini App authorization error"
        );

        console.error(error);

    }

}


function renderUser() {

    if (!state) return;


    const name =
        state.first_name ||
        state.username ||
        "EHAN USER";


    document.getElementById(
        "userName"
    ).innerText = name;


    document.getElementById(
        "userId"
    ).innerText =
        "ID: " +
        state.user_id;


    document.getElementById(
        "avatar"
    ).innerText =
        name
            .charAt(0)
            .toUpperCase();


    document.getElementById(
        "balance"
    ).innerText =
        Number(
            state.balance
        ).toFixed(2);


    document.getElementById(
        "profileName"
    ).innerText =
        name;


    document.getElementById(
        "profileId"
    ).innerText =
        state.user_id;


    document.getElementById(
        "profileUsername"
    ).innerText =
        state.username
            ? "@" + state.username
            : "No username";


    document.getElementById(
        "profileBalance"
    ).innerText =
        Number(
            state.balance
        ).toFixed(2);


    document.getElementById(
        "profileRefs"
    ).innerText =
        state.referral_count || 0;


    document.getElementById(
        "refCount"
    ).innerText =
        state.referral_count || 0;


    referralLink =
        state.referral_link;


    document.getElementById(
        "refLink"
    ).innerText =
        referralLink;


    document.getElementById(
        "rate"
    ).innerText =
        Number(
            state.mining_rate
        ).toFixed(4);


    document.getElementById(
        "minerRate"
    ).innerText =
        Number(
            state.mining_rate
        ).toFixed(4)
        + " P/s";

}


function startMiningClock() {

    if (miningTimer) {

        clearInterval(
            miningTimer
        );

    }


    updateMining();


    miningTimer =
        setInterval(
            updateMining,
            1000
        );

}


function updateMining() {

    if (!state) return;


    const start =
        state.mining_started;


    if (!start) {

        document.getElementById(
            "earned"
        ).innerText =
            "+0.0000";

        return;

    }


    const startTime =
        new Date(
            start + "Z"
        ).getTime();


    let elapsed =
        (
            Date.now()
            -
            startTime
        ) / 1000;


    elapsed =
        Math.max(
            0,
            Math.min(
                elapsed,
                state.max_seconds
            )
        );


    const earned =
        elapsed *
        Number(
            state.mining_rate
        );


    document.getElementById(
        "earned"
    ).innerText =
        "+" +
        earned.toFixed(4);


    if (
        elapsed >=
        state.max_seconds
    ) {

        document.getElementById(
            "miningStatus"
        ).innerText =
            "READY TO CLAIM";

    }

}


async function claimMining() {

    try {

        const button =
            document.querySelector(
                ".claim"
            );

        button.disabled = true;

        button.innerText =
            "⏳ CLAIMING...";


        const result =
            await api(
                "/api/claim"
            );


        state.balance =
            result.balance;


        state.mining_started =
            result.mining_started;


        renderUser();

        toast(
            "🎉 +" +
            Number(
                result.reward
            ).toFixed(4)
            +
            " Points claimed!"
        );


    } catch(error) {

        toast(
            error.message
        );

    }


    const button =
        document.querySelector(
            ".claim"
        );

    button.disabled = false;

    button.innerText =
        "⚡ CLAIM";

}


function openPage(page) {

    document
        .querySelectorAll(".page")
        .forEach(
            el => {
                el.classList.remove(
                    "active"
                );
            }
        );


    const target =
        document.getElementById(
            "page-" + page
        );


    if (target) {

        target.classList.add(
            "active"
        );

    }


    document
        .querySelectorAll(".nav")
        .forEach(
            el => {

                el.classList.remove(
                    "active"
                );

                if (
                    el.dataset.page
                    ===
                    page
                ) {

                    el.classList.add(
                        "active"
                    );

                }

            }
        );


    if (page === "tasks") {

        loadTasks();

    }

}


async function loadTasks() {

    try {

        const data =
            await api(
                "/api/tasks"
            );


        const list =
            document.getElementById(
                "taskList"
            );


        if (!data.tasks.length) {

            list.innerHTML =
                `
                <div class="card">
                    <div
                        class="loading"
                    >
                        📋 No active tasks
                        right now.
                    </div>
                </div>
                `;

            return;

        }


        list.innerHTML =
            data.tasks.map(
                task =>
                `
                <div class="task">

                    <div class="taskTitle">
                        ${escapeHtml(
                            task.title
                        )}
                    </div>

                    <div class="taskDesc">
                        ${escapeHtml(
                            task.description
                        )}
                    </div>

                    <div class="taskBottom">

                        <span class="reward">
                            +${Number(
                                task.reward
                            ).toFixed(2)}
                            Points
                        </span>

                        <button
                            class="smallBtn"
                            onclick="
                                submitTask(
                                    ${task.id}
                                )
                            "
                        >
                            DONE
                        </button>

                    </div>

                </div>
                `
            ).join("");


    } catch(error) {

        document.getElementById(
            "taskList"
        ).innerHTML =
            `
            <div class="card">
                <div class="loading">
                    Unable to load tasks.
                </div>
            </div>
            `;

    }

}


async function submitTask(id) {

    try {

        const result =
            await api(
                "/api/submit_task",
                {
                    task_id: id
                }
            );


        toast(
            result.message
        );


    } catch(error) {

        toast(
            error.message
        );

    }

}


function copyReferral() {

    if (!referralLink) return;


    navigator.clipboard
        .writeText(
            referralLink
        )
        .then(
            () => {
                toast(
                    "🔗 Referral link copied!"
                );
            }
        );

}


function openMore(type) {

    const modal =
        document.getElementById(
            "modal"
        );

    const title =
        document.getElementById(
            "sheetTitle"
        );

    const body =
        document.getElementById(
            "sheetBody"
        );


    if (type === "withdraw") {

        title.innerText =
            "💸 Withdraw";


        body.innerHTML =
            `
            <div
                style="
                    color:#8fa99c;
                    font-size:12px;
                    margin-bottom:12px;
                "
            >
                Minimum:
                ${MIN_WITHDRAWAL}
                Points
            </div>

            ${withdrawButton(
                "🟡",
                "Binance"
            )}

            ${withdrawButton(
                "🟢",
                "bKash"
            )}

            ${withdrawButton(
                "🔴",
                "Nagad"
            )}

            ${withdrawButton(
                "🔵",
                "PayPal"
            )}
            `;

    }


    else if (type === "daily") {

        title.innerText =
            "🎁 Daily Bonus";


        body.innerHTML =
            `
            <p
                style="
                    color:#8fa99c;
                    font-size:13px;
                "
            >
                প্রতিদিন একবার
                ${DAILY_REWARD}
                Points bonus নিতে পারবেন।
            </p>

            <button
                class="primary"
                onclick="claimDaily()"
            >
                🎁 CLAIM DAILY BONUS
            </button>
            `;

    }


    else {

        title.innerText =
            "⚡ More Features";


        body.innerHTML =
            `
            <button
                class="action"
                style="
                    width:100%;
                    margin-bottom:8px;
                "
                onclick="openQuiz()"
            >
                🌍 International Quiz
            </button>

            <button
                class="action"
                style="
                    width:100%;
                    margin-bottom:8px;
                "
                onclick="openGame()"
            >
                🎮 Number Game
            </button>

            <button
                class="action"
                style="
                    width:100%;
                "
                onclick="openLeaderboard()"
            >
                🏆 Leaderboard
            </button>
            `;

    }


    modal.classList.add(
        "show"
    );

}


function withdrawButton(
    icon,
    method
) {

    return `
        <div
            class="withdrawRow"
            onclick="
                withdrawForm(
                    '${method}'
                )
            "
        >

            <div
                class="withdrawIcon"
            >
                ${icon}
            </div>

            <div>

                <b>
                    ${method}
                </b>

                <div
                    style="
                        color:#8fa99c;
                        font-size:11px;
                    "
                >
                    Select payment method
                </div>

            </div>

        </div>
    `;

}


function withdrawForm(method) {

    const title =
        document.getElementById(
            "sheetTitle"
        );

    const body =
        document.getElementById(
            "sheetBody"
        );


    title.innerText =
        "💸 " + method;


    body.innerHTML =
        `
        <input
            id="wdAmount"
            class="input"
            type="number"
            placeholder="Amount"
        >

        <input
            id="wdAccount"
            class="input"
            type="text"
            placeholder="
                ${method === "PayPal"
                    ? "PayPal Email"
                    : "Account / Number / ID"
                }
            "
        >

        <button
            class="primary"
            onclick="
                submitWithdrawal(
                    '${method}'
                )
            "
        >
            SEND WITHDRAWAL REQUEST
        </button>
        `;

}


async function submitWithdrawal(
    method
) {

    const amount =
        Number(
            document.getElementById(
                "wdAmount"
            ).value
        );


    const account =
        document.getElementById(
            "wdAccount"
        ).value.trim();


    if (
        !amount ||
        amount < MIN_WITHDRAWAL
    ) {

        toast(
            "Minimum withdrawal is "
            +
            MIN_WITHDRAWAL
            +
            " Points"
        );

        return;

    }


    if (!account) {

        toast(
            "Account information দিন"
        );

        return;

    }


    try {

        const result =
            await api(
                "/api/withdraw",
                {
                    amount,
                    method,
                    account
                }
            );


        state.balance =
            result.balance;


        renderUser();

        closeModal();


        toast(
            "✅ Withdrawal request submitted"
        );


    } catch(error) {

        toast(
            error.message
        );

    }

}


async function claimDaily() {

    try {

        const result =
            await api(
                "/api/daily"
            );


        state.balance =
            result.balance;


        renderUser();

        closeModal();


        toast(
            "🎁 Daily bonus claimed!"
        );


    } catch(error) {

        toast(
            error.message
        );

    }

}


async function openQuiz() {

    try {

        const data =
            await api(
                "/api/quiz"
            );


        document.getElementById(
            "sheetTitle"
        ).innerText =
            "🌍 International Quiz";


        document.getElementById(
            "sheetBody"
        ).innerHTML =
            `
            <div
                style="
                    font-weight:900;
                    line-height:1.5;
                "
            >
                ${escapeHtml(
                    data.question
                )}
            </div>

            <div
                style="
                    margin-top:15px;
                "
            >

                ${data.options.map(
                    (x,i) =>
                    `
                    <button
                        class="action"
                        style="
                            width:100%;
                            margin-bottom:8px;
                        "
                        onclick="
                            answerQuiz(
                                ${i}
                            )
                        "
                    >
                        ${String.fromCharCode(
                            65+i
                        )}.
                        ${escapeHtml(x)}
                    </button>
                    `
                ).join("")}

            </div>
            `;

        document.getElementById(
            "modal"
        ).classList.add(
            "show"
        );


    } catch(error) {

        toast(
            error.message
        );

    }

}


async function answerQuiz(
    answer
) {

    try {

        const result =
            await api(
                "/api/quiz_answer",
                {
                    answer
                }
            );


        if (
            result.correct
        ) {

            state.balance =
                result.balance;

            renderUser();

            toast(
                "🎉 Correct! +"
                +
                QUIZ_REWARD
                +
                " Points"
            );

        }

        else {

            toast(
                "❌ Wrong answer"
            );

        }


        closeModal();


    } catch(error) {

        toast(
            error.message
        );

    }

}


function openGame() {

    document.getElementById(
        "sheetTitle"
    ).innerText =
        "🎮 Number Game";


    document.getElementById(
        "sheetBody"
    ).innerHTML =
        `
        <p
            style="
                color:#8fa99c;
            "
        >
            1 থেকে 5 এর মধ্যে
            একটি সংখ্যা বেছে নিন।
        </p>

        <div class="grid">

            ${[1,2,3,4,5].map(
                n =>
                `
                <button
                    class="action"
                    onclick="
                        playGame(${n})
                    "
                >
                    🎯 ${n}
                </button>
                `
            ).join("")}

        </div>
        `;


    document.getElementById(
        "modal"
    ).classList.add(
        "show"
    );

}


async function playGame(
    number
) {

    try {

        const result =
            await api(
                "/api/guess",
                {
                    number
                }
            );


        if (result.win) {

            state.balance =
                result.balance;

            renderUser();

            toast(
                "🎉 You Win! +"
                +
                GAME_REWARD
                +
                " Points"
            );

        }

        else {

            toast(
                "😔 You lost. Number was "
                +
                result.correct
            );

        }


        closeModal();


    } catch(error) {

        toast(
            error.message
        );

    }

}


async function openLeaderboard() {

    try {

        const data =
            await api(
                "/api/leaderboard"
            );


        document.getElementById(
            "sheetTitle"
        ).innerText =
            "🏆 Leaderboard";


        document.getElementById(
            "sheetBody"
        ).innerHTML =
            data.rows.map(
                (row,i) =>
                `
                <div
                    class="profileRow"
                >

                    <b>
                        ${i+1}.
                        ${escapeHtml(
                            row.name
                        )}
                    </b>

                    <span>
                        ${Number(
                            row.balance
                        ).toFixed(2)}
                        Points
                    </span>

                </div>
                `
            ).join("");


        document.getElementById(
            "modal"
        ).classList.add(
            "show"
        );


    } catch(error) {

        toast(
            error.message
        );

    }

}


function closeModal() {

    document.getElementById(
        "modal"
    ).classList.remove(
        "show"
    );

}


function escapeHtml(
    value
) {

    return String(
        value || ""
    )
    .replaceAll(
        "&",
        "&amp;"
    )
    .replaceAll(
        "<",
        "&lt;"
    )
    .replaceAll(
        ">",
        "&gt;"
    )
    .replaceAll(
        '"',
        "&quot;"
    )
    .replaceAll(
        "'",
        "&#039;"
    );

}


function closeModalEvent(
    event
) {

    if (
        event.target.id
        ===
        "modal"
    ) {

        closeModal();

    }

}


function closeModal(
    event
) {

    if (
        event &&
        event.target &&
        event.target.id !== "modal"
    ) {

        return;

    }

    document.getElementById(
        "modal"
    ).classList.remove(
        "show"
    );

}


loadMe();


</script>

</body>

</html>
"""


# ============================================================
# MINI APP HTTP SERVER
# ============================================================

class AppServer(
    BaseHTTPRequestHandler
):


    def send_json(
        self,
        data,
        status=200
    ):

        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")


        self.send_response(
            status
        )


        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )


        self.send_header(
            "Content-Length",
            str(len(body))
        )


        self.send_header(
            "Cache-Control",
            "no-store"
        )


        self.end_headers()


        self.wfile.write(
            body
        )


    def read_json(self):

        length = int(
            self.headers.get(
                "Content-Length",
                "0"
            )
        )

        raw = self.rfile.read(
            length
        )

        if not raw:
            return {}

        return json.loads(
            raw.decode("utf-8")
        )


    def get_user_from_body(
        self,
        body
    ):

        init_data =
            body.get(
                "initData",
                ""
            )

        user =
            validate_init_data(
                init_data
            )

        if not user:

            return None

        add_user(
            type(
                "User",
                (),
                {
                    "id":
                        int(
                            user["id"]
                        ),

                    "username":
                        user.get(
                            "username",
                            ""
                        ),

                    "first_name":
                        user.get(
                            "first_name",
                            ""
                        )
                }
            )()
        )

        return user


    def do_GET(self):

        path =
            urllib.parse.urlparse(
                self.path
            ).path


        if path == "/":

            body =
                HTML.encode(
                    "utf-8"
                )


            self.send_response(
                200
            )


            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )


            self.send_header(
                "Content-Length",
                str(len(body))
            )


            self.end_headers()


            self.wfile.write(
                body
            )

            return


        if path == "/health":

            body =
                b"EHAN EARN BOT + MINI APP OK"


            self.send_response(
                200
            )


            self.send_header(
                "Content-Type",
                "text/plain"
            )


            self.send_header(
                "Content-Length",
                str(len(body))
            )


            self.end_headers()


            self.wfile.write(
                body
            )

            return


        self.send_response(
            404
        )

        self.end_headers()


    def do_POST(self):

        path =
            urllib.parse.urlparse(
                self.path
            ).path


        try:

            body =
                self.read_json()


        except Exception:

            self.send_json(
                {
                    "error":
                        "Invalid request"
                },
                400
            )

            return


        user =
            self.get_user_from_body(
                body
            )


        if not user:

            self.send_json(
                {
                    "error":
                        "Telegram authorization failed. Open the app from Telegram."
                },
                401
            )

            return


        user_id =
            int(
                user["id"]
            )


        # -------------------------
        # ME
        # -------------------------

        if path == "/api/me":

            start_mining_if_needed(
                user_id
            )

            row =
                get_user(
                    user_id
                )


            info =
                mining_info(
                    user_id
                )


            referral_link =
                "https://t.me/" +
                BOT_USERNAME +
                "?start=" +
                str(user_id)


            self.send_json({

                "user_id":
                    user_id,

                "username":
                    row["username"] or "",

                "first_name":
                    row["first_name"] or "",

                "balance":
                    float(
                        row["balance"] or 0
                    ),

                "referral_count":
                    int(
                        row["referral_count"] or 0
                    ),

                "referral_link":
                    referral_link,

                "mining_started":
                    row["mining_started"],

                "mining_rate":
                    info["rate"],

                "max_seconds":
                    MINING_MAX_SECONDS

            })

            return


        # -------------------------
        # CLAIM
        # -------------------------

        if path == "/api/claim":

            reward =
                claim_mining(
                    user_id
                )


            row =
                get_user(
                    user_id
                )


            self.send_json({

                "reward":
                    reward,

                "balance":
                    float(
                        row["balance"] or 0
                    ),

                "mining_started":
                    row["mining_started"]

            })

            return


        # -------------------------
        # TASKS
        # -------------------------

        if path == "/api/tasks":

            conn = db()


            rows =
                conn.execute("""
                    SELECT
                        id,
                        title,
                        description,
                        reward
                    FROM tasks
                    WHERE active=1
                    ORDER BY id DESC
                """).fetchall()


            conn.close()


            self.send_json({

                "tasks": [

                    {
                        "id":
                            row["id"],

                        "title":
                            row["title"],

                        "description":
                            row["description"],

                        "reward":
                            float(
                                row["reward"]
                                or 0
                            )

                    }

                    for row in rows

                ]

            })

            return


        # -------------------------
        # SUBMIT TASK
        # -------------------------

        if path == "/api/submit_task":

            task_id =
                int(
                    body.get(
                        "task_id",
                        0
                    )
                )


            conn = db()


            task =
                conn.execute("""
                    SELECT *
                    FROM tasks
                    WHERE id=?
                    AND active=1
                """, (
                    task_id,
                )).fetchone()


            if not task:

                conn.close()


                self.send_json(
                    {
                        "error":
                            "Task not found"
                    },
                    404
                )

                return


            existing =
                conn.execute("""
                    SELECT id
                    FROM task_submissions
                    WHERE user_id=?
                    AND task_id=?
                    AND status IN
                        ('Pending','Approved')
                """, (
                    user_id,
                    task_id
                )).fetchone()


            if existing:

                conn.close()


                self.send_json(
                    {
                        "error":
                            "You already submitted this task"
                    },
                    400
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
                VALUES
                (?, ?, 'Pending', ?)
            """, (
                user_id,
                task_id,
                datetime.utcnow().isoformat()
            ))


            conn.commit()

            conn.close()


            self.send_json({

                "message":
                    "✅ Task submitted. Waiting for admin approval."

            })

            return


        # -------------------------
        # DAILY
        # -------------------------

        if path == "/api/daily":

            today =
                datetime.utcnow().date().isoformat()


            conn = db()


            row =
                conn.execute("""
                    SELECT last_daily
                    FROM users
                    WHERE user_id=?
                """, (
                    user_id,
                )).fetchone()


            if (
                row
                and
                row["last_daily"]
                ==
                today
            ):

                conn.close()


                self.send_json(
                    {
                        "error":
                            "Daily bonus already claimed today."
                    },
                    400
                )

                return


            conn.execute("""
                UPDATE users
                SET balance=balance+?,
                    last_daily=?
                WHERE user_id=?
            """, (
                DAILY_REWARD,
                today,
                user_id
            ))


            conn.commit()

            conn.close()


            self.send_json({

                "reward":
                    DAILY_REWARD,

                "balance":
                    get_balance(
                        user_id
                    )

            })

            return


        # -------------------------
        # WITHDRAW
        # -------------------------

        if path == "/api/withdraw":

            try:

                amount =
                    float(
                        body.get(
                            "amount",
                            0
                        )
                    )

            except Exception:

                amount = 0


            method =
                str(
                    body.get(
                        "method",
                        ""
                    )
                )


            account =
                str(
                    body.get(
                        "account",
                        ""
                    )
                ).strip()


            if amount < MIN_WITHDRAWAL:

                self.send_json(
                    {
                        "error":
                            f"Minimum withdrawal is {MIN_WITHDRAWAL} Points"
                    },
                    400
                )

                return


            if method not in WITHDRAW_METHODS:

                self.send_json(
                    {
                        "error":
                            "Invalid payment method"
                    },
                    400
                )

                return


            if not account:

                self.send_json(
                    {
                        "error":
                            "Account information required"
                    },
                    400
                )

                return


            conn = db()


            row =
                conn.execute("""
                    SELECT balance
                    FROM users
                    WHERE user_id=?
                """, (
                    user_id,
                )).fetchone()


            if (
                not row
                or
                float(
                    row["balance"] or 0
                )
                <
                amount
            ):

                conn.close()


                self.send_json(
                    {
                        "error":
                            "Insufficient balance"
                    },
                    400
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


            conn.execute("""
                INSERT INTO withdrawals
                (
                    user_id,
                    amount,
                    method,
                    account,
                    status,
                    created_at
                )
                VALUES
                (?, ?, ?, ?, 'Pending', ?)
            """, (
                user_id,
                amount,
                method,
                account,
                datetime.utcnow().isoformat()
            ))


            conn.commit()

            conn.close()


            self.send_json({

                "balance":
                    get_balance(
                        user_id
                    )

            })

            return


        # -------------------------
        # QUIZ
        # -------------------------

        if path == "/api/quiz":

            questions = [

                (
                    "What is the capital of Bangladesh?",
                    [
                        "Dhaka",
                        "Chattogram",
                        "Rajshahi",
                        "Sylhet"
                    ],
                    0
                ),

                (
                    "Which planet is known as the Red Planet?",
                    [
                        "Earth",
                        "Mars",
                        "Jupiter",
                        "Venus"
                    ],
                    1
                ),

                (
                    "How many days are there in a week?",
                    [
                        "5",
                        "6",
                        "7",
                        "8"
                    ],
                    2
                ),

                (
                    "Which is the largest ocean?",
                    [
                        "Atlantic",
                        "Indian",
                        "Pacific",
                        "Arctic"
                    ],
                    2
                ),

                (
                    "How many continents are there?",
                    [
                        "5",
                        "6",
                        "7",
                        "8"
                    ],
                    2
                )

            ]


            question, options, answer =
                random.choice(
                    questions
                )


            conn = db()


            conn.execute("""
                UPDATE users
                SET quiz_question=?,
                    quiz_answer=?
                WHERE user_id=?
            """, (
                question,
                answer,
                user_id
            ))


            conn.commit()

            conn.close()


            self.send_json({

                "question":
                    question,

                "options":
                    options

            })

            return


        # -------------------------
        # QUIZ ANSWER
        # -------------------------

        if path == "/api/quiz_answer":

            answer =
                int(
                    body.get(
                        "answer",
                        -1
                    )
                )


            conn = db()


            row =
                conn.execute("""
                    SELECT quiz_answer
                    FROM users
                    WHERE user_id=?
                """, (
                    user_id,
                )).fetchone()


            correct =
                (
                    row
                    and
                    row["quiz_answer"]
                    is not None
                    and
                    answer
                    ==
                    int(
                        row["quiz_answer"]
                    )
                )


            if correct:

                conn.execute("""
                    UPDATE users
                    SET balance=balance+?,
                        quiz_answer=NULL
                    WHERE user_id=?
                """, (
                    QUIZ_REWARD,
                    user_id
                ))

            else:

                conn.execute("""
                    UPDATE users
                    SET quiz_answer=NULL
                    WHERE user_id=?
                """, (
                    user_id
                ))


            conn.commit()

            conn.close()


            self.send_json({

                "correct":
                    bool(correct),

                "balance":
                    get_balance(
                        user_id
                    )

            })

            return


        # -------------------------
        # GAME
        # -------------------------

        if path == "/api/guess":

            number =
                int(
                    body.get(
                        "number",
                        0
                    )
                )


            if number < 1 or number > 5:

                self.send_json(
                    {
                        "error":
                            "Choose 1 to 5"
                    },
                    400
                )

                return


            correct =
                random.randint(
                    1,
                    5
                )


            win =
                number == correct


            conn = db()


            conn.execute("""
                INSERT INTO game_stats
                (
                    user_id,
                    wins,
                    games
                )
                VALUES (?, ?, 1)

                ON CONFLICT(user_id)
                DO UPDATE SET
                    games=games+1,
                    wins=wins+excluded.wins
            """, (
                user_id,
                1 if win else 0
            ))


            conn.commit()

            conn.close()


            if win:

                add_balance(
                    user_id,
                    GAME_REWARD
                )


            self.send_json({

                "win":
                    win,

                "correct":
                    correct,

                "balance":
                    get_balance(
                        user_id
                    )

            })

            return


        # -------------------------
        # LEADERBOARD
        # -------------------------

        if path == "/api/leaderboard":

            conn = db()


            rows =
                conn.execute("""
                    SELECT
                        first_name,
                        username,
                        balance
                    FROM users
                    ORDER BY balance DESC
                    LIMIT 10
                """).fetchall()


            conn.close()


            result = []


            for row in rows:

                result.append({

                    "name":
                        row["first_name"]
                        or
                        row["username"]
                        or
                        "User",

                    "balance":
                        float(
                            row["balance"]
                            or 0
                        )

                })


            self.send_json({

                "rows":
                    result

            })

            return


        self.send_json(
            {
                "error":
                    "API endpoint not found"
            },
            404
        )


    def log_message(
        self,
        format,
        *args
    ):

        pass


def start_http_server():

    server =
        ThreadingHTTPServer(
            (
                "0.0.0.0",
                PORT
            ),
            AppServer
        )


    print(
        "🌐 EHAN EARN Mini App running on port",
        PORT
    )


    server.serve_forever()


# ============================================================
# TELEGRAM BOT
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    referral_id = None


    if context.args:

        try:

            referral_id =
                int(
                    context.args[0]
                )

        except Exception:

            referral_id = None


    add_user(
        update.effective_user,
        referral_id
    )


    start_mining_if_needed(
        update.effective_user.id
    )


    keyboard = [

        [
            InlineKeyboardButton(
                "🚀 OPEN EHAN EARN APP",
                web_app=WebAppInfo(
                    url=WEBAPP_URL
                )
            )
        ]

    ]


    await update.message.reply_text(

        "🎉 WELCOME TO EHAN EARN!\n\n"

        "⛏️ আপনার Mining এখন active.\n"
        "💰 Points earn করুন\n"
        "👥 Friends invite করুন\n"
        "📋 Tasks complete করুন\n\n"

        "নিচের button চাপলে "
        "আপনার নতুন EHAN EARN dashboard খুলবে। 👇",

        reply_markup=
        InlineKeyboardMarkup(
            keyboard
        )
    )


async def balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(
        update.effective_user
    )


    await update.message.reply_text(

        "💰 YOUR BALANCE\n\n"

        f"{get_balance(update.effective_user.id):.2f} Points\n\n"

        "🚀 Dashboard খুলতে /start দিন।"
    )


async def referral(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(
        update.effective_user
    )


    row =
        get_user(
            update.effective_user.id
        )


    link =
        "https://t.me/" +
        BOT_USERNAME +
        "?start=" +
        str(
            update.effective_user.id
        )


    await update.message.reply_text(

        "👥 REFERRAL\n\n"

        f"🔗 {link}\n\n"

        f"👤 Referrals: "
        f"{row['referral_count'] or 0}\n\n"

        f"🎁 Reward per referral: "
        f"+{REFERRAL_REWARD} Points"
    )


async def mining(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(
        update.effective_user
    )


    user_id =
        update.effective_user.id


    start_mining_if_needed(
        user_id
    )


    info =
        mining_info(
            user_id
        )


    await update.message.reply_text(

        "⛏️ MINING\n\n"

        f"⚡ Rate: "
        f"{info['rate']:.4f} Points/sec\n\n"

        f"💰 Current Mining: "
        f"{info['earned']:.4f} Points\n\n"

        "🚀 আপনার Mining dashboard-এ "
        "live দেখাবে।"
    )


async def daily(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(
        update.effective_user
    )


    user_id =
        update.effective_user.id


    today =
        datetime.utcnow().date().isoformat()


    conn = db()


    row =
        conn.execute("""
            SELECT last_daily
            FROM users
            WHERE user_id=?
        """, (
            user_id,
        )).fetchone()


    if (
        row
        and
        row["last_daily"]
        ==
        today
    ):

        conn.close()


        await update.message.reply_text(
            "🎁 আজকের Daily Bonus নেওয়া হয়েছে।"
        )

        return


    conn.execute("""
        UPDATE users
        SET balance=balance+?,
            last_daily=?
        WHERE user_id=?
    """, (
        DAILY_REWARD,
        today,
        user_id
    ))


    conn.commit()

    conn.close()


    await update.message.reply_text(

        "🎁 DAILY BONUS!\n\n"

        f"+{DAILY_REWARD} Points\n\n"

        f"💰 Balance: "
        f"{get_balance(user_id):.2f}"
    )


# ============================================================
# BOT QUIZ
# ============================================================

QUIZ_DATA = [

    (
        "🌍 What is the capital of Bangladesh?",
        [
            "Dhaka",
            "Chattogram",
            "Rajshahi",
            "Sylhet"
        ],
        0
    ),

    (
        "🔴 Which planet is known as the Red Planet?",
        [
            "Earth",
            "Mars",
            "Jupiter",
            "Venus"
        ],
        1
    ),

    (
        "📅 How many days are there in a week?",
        [
            "5",
            "6",
            "7",
            "8"
        ],
        2
    ),

    (
        "🌊 Which is the largest ocean?",
        [
            "Atlantic",
            "Indian",
            "Pacific",
            "Arctic"
        ],
        2
    )

]


async def quiz(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(
        update.effective_user
    )


    question, options, answer =
        random.choice(
            QUIZ_DATA
        )


    context.user_data[
        "quiz_answer"
    ] = answer


    keyboard = []


    for i, option in enumerate(
        options
    ):

        keyboard.append([

            InlineKeyboardButton(
                f"{chr(65+i)}) {option}",
                callback_data=
                f"quiz:{i}"
            )

        ])


    await update.message.reply_text(

        "🌍 INTERNATIONAL QUIZ\n\n"

        f"{question}\n\n"

        "সঠিক উত্তর নির্বাচন করুন 👇",

        reply_markup=
        InlineKeyboardMarkup(
            keyboard
        )
    )


async def quiz_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query =
        update.callback_query


    await query.answer()


    selected =
        int(
            query.data.split(":")[1]
        )


    correct =
        context.user_data.pop(
            "quiz_answer",
            -1
        )


    if selected == correct:

        add_balance(
            query.from_user.id,
            QUIZ_REWARD
        )


        await query.edit_message_text(

            "🎉 সঠিক উত্তর!\n\n"

            f"🎁 +{QUIZ_REWARD} Points\n"

            f"💰 Balance: "
            f"{get_balance(query.from_user.id):.2f}"
        )

    else:

        await query.edit_message_text(
            "❌ ভুল উত্তর!\n\n"
            "আবার /quiz দিন।"
        )


# ============================================================
# TASK COMMANDS
# ============================================================

async def tasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(
        update.effective_user
    )


    conn = db()


    rows =
        conn.execute("""
            SELECT
                id,
                title,
                description,
                reward
            FROM tasks
            WHERE active=1
            ORDER BY id DESC
        """).fetchall()


    conn.close()


    if not rows:

        await update.message.reply_text(
            "📋 বর্তমানে কোনো active task নেই।"
        )

        return


    text =
        "📋 AVAILABLE TASKS\n\n"


    for row in rows:

        text += (

            f"🆔 {row['id']}\n"

            f"📌 {row['title']}\n"

            f"📝 {row['description']}\n"

            f"🎁 {row['reward']:.2f} Points\n"

            f"/done {row['id']}\n\n"

        )


    await update.message.reply_text(
        text
    )


async def done_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "/done TASK_ID"
        )

        return


    try:

        task_id =
            int(
                context.args[0]
            )

    except Exception:

        await update.message.reply_text(
            "❌ Invalid Task ID"
        )

        return


    user_id =
        update.effective_user.id


    conn = db()


    task =
        conn.execute("""
            SELECT *
            FROM tasks
            WHERE id=?
            AND active=1
        """, (
            task_id,
        )).fetchone()


    if not task:

        conn.close()


        await update.message.reply_text(
            "❌ Task পাওয়া যায়নি।"
        )

        return


    existing =
        conn.execute("""
            SELECT id
            FROM task_submissions
            WHERE user_id=?
            AND task_id=?
            AND status IN
                ('Pending','Approved')
        """, (
            user_id,
            task_id
        )).fetchone()


    if existing:

        conn.close()


        await update.message.reply_text(
            "⚠️ এই Task আগে submit করেছেন।"
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
        VALUES
        (?, ?, 'Pending', ?)
    """, (
        user_id,
        task_id,
        datetime.utcnow().isoformat()
    ))


    conn.commit()

    conn.close()


    await update.message.reply_text(
        "✅ Task submitted.\n"
        "⏳ Admin approval-এর অপেক্ষায়।"
    )


# ============================================================
# GAMES
# ============================================================

async def games(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "🎮 GAMES\n\n"

        "Number Guess Game\n\n"

        "১ থেকে ৫ এর মধ্যে guess করুন:\n\n"

        "/guess 3"
    )


async def guess(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "/guess 1 থেকে 5"
        )

        return


    try:

        number =
            int(
                context.args[0]
            )

    except Exception:

        await update.message.reply_text(
            "❌ Invalid number"
        )

        return


    if number < 1 or number > 5:

        await update.message.reply_text(
            "❌ 1 থেকে 5 দিন।"
        )

        return


    correct =
        random.randint(
            1,
            5
        )


    win =
        number == correct


    user_id =
        update.effective_user.id


    conn = db()


    conn.execute("""
        INSERT INTO game_stats
        (
            user_id,
            wins,
            games
        )
        VALUES (?, ?, 1)

        ON CONFLICT(user_id)
        DO UPDATE SET
            games=games+1,
            wins=wins+excluded.wins
    """, (
        user_id,
        1 if win else 0
    ))


    conn.commit()

    conn.close()


    if win:

        add_balance(
            user_id,
            GAME_REWARD
        )


        await update.message.reply_text(

            "🎉 YOU WIN!\n\n"

            f"🎁 +{GAME_REWARD} Points\n"

            f"💰 Balance: "
            f"{get_balance(user_id):.2f}"
        )

    else:

        await update.message.reply_text(

            "😔 You Lost!\n\n"

            f"Correct number: {correct}"
        )


# ============================================================
# LEADERBOARD
# ============================================================

async def leaderboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    conn = db()


    rows =
        conn.execute("""
            SELECT
                first_name,
                username,
                balance
            FROM users
            ORDER BY balance DESC
            LIMIT 10
        """).fetchall()


    conn.close()


    text =
        "🏆 TOP 10\n\n"


    for i, row in enumerate(
        rows,
        1
    ):

        name =
            row["first_name"]
            or
            row["username"]
            or
            "User"


        text += (

            f"{i}. "
            f"{name} — "
            f"{row['balance']:.2f} Points\n"

        )


    await update.message.reply_text(
        text
    )


# ============================================================
# WITHDRAW COMMAND
# ============================================================

async def withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [

        [
            InlineKeyboardButton(
                "🟡 Binance",
                callback_data=
                "wd:Binance"
            ),

            InlineKeyboardButton(
                "🟢 bKash",
                callback_data=
                "wd:bKash"
            )
        ],

        [
            InlineKeyboardButton(
                "🔴 Nagad",
                callback_data=
                "wd:Nagad"
            ),

            InlineKeyboardButton(
                "🔵 PayPal",
                callback_data=
                "wd:PayPal"
            )
        ]

    ]


    await update.message.reply_text(

        "💸 WITHDRAWAL\n\n"

        f"💰 Balance: "
        f"{get_balance(update.effective_user.id):.2f}\n\n"

        f"🔻 Minimum: "
        f"{MIN_WITHDRAWAL} Points\n\n"

        "Payment method নির্বাচন করুন 👇",

        reply_markup=
        InlineKeyboardMarkup(
            keyboard
        )
    )


async def withdrawal_method(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query =
        update.callback_query


    await query.answer()


    method =
        query.data.split(":")[1]


    await query.message.reply_text(

        f"💳 {method}\n\n"

        f"/requestwithdraw "
        f"{MIN_WITHDRAWAL} "
        f"{method} "
        f"YOUR_ACCOUNT\n\n"

        "উদাহরণ:\n"

        f"/requestwithdraw "
        f"100 {method} YOUR_ACCOUNT"
    )


async def request_withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(
        context.args
    ) < 3:

        await update.message.reply_text(

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

        amount =
            float(
                context.args[0]
            )

    except Exception:

        await update.message.reply_text(
            "❌ Invalid amount"
        )

        return


    method =
        context.args[1]


    if method.lower() == "binance":
        method = "Binance"

    elif method.lower() == "bkash":
        method = "bKash"

    elif method.lower() == "nagad":
        method = "Nagad"

    elif method.lower() == "paypal":
        method = "PayPal"

    else:

        await update.message.reply_text(
            "❌ Invalid payment method"
        )

        return


    account =
        " ".join(
            context.args[2:]
        )


    user_id =
        update.effective_user.id


    if amount < MIN_WITHDRAWAL:

        await update.message.reply_text(

            f"❌ Minimum "
            f"{MIN_WITHDRAWAL} Points"
        )

        return


    conn = db()


    row =
        conn.execute("""
            SELECT balance
            FROM users
            WHERE user_id=?
        """, (
            user_id,
        )).fetchone()


    if (
        not row
        or
        float(
            row["balance"] or 0
        )
        < amount
    ):

        conn.close()


        await update.message.reply_text(
            "❌ Insufficient balance"
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


    cursor =
        conn.execute("""
            INSERT INTO withdrawals
            (
                user_id,
                amount,
                method,
                account,
                status,
                created_at
            )
            VALUES
            (?, ?, ?, ?, 'Pending', ?)
        """, (
            user_id,
            amount,
            method,
            account,
            datetime.utcnow().isoformat()
        ))


    withdrawal_id =
        cursor.lastrowid


    conn.commit()

    conn.close()


    await update.message.reply_text(

        "✅ WITHDRAWAL REQUEST\n\n"

        f"🆔 ID: {withdrawal_id}\n"
        f"💰 Amount: {amount:.2f}\n"
        f"💳 Method: {method}\n"
        f"📱 Account: {account}\n"
        "⏳ Status: Pending"
    )


# ============================================================
# BASIC COMMANDS
# ============================================================

async def myid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        f"🆔 Telegram User ID:\n\n"
        f"{update.effective_user.id}"
    )


async def rules(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "📜 EHAN EARN RULES\n\n"

        "1️⃣ Fake account ব্যবহার করা যাবে না।\n"
        "2️⃣ Referral abuse করা যাবে না।\n"
        "3️⃣ Task fraud করা যাবে না।\n"
        "4️⃣ Withdrawal যাচাই করা হবে।\n"
        "5️⃣ Points-এর value ও withdrawal rules "
        "official system অনুযায়ী হবে।"
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "🆘 EHAN EARN HELP\n\n"

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
        "/myid\n"
        "/rules\n\n"

        "🚀 অথবা /start দিয়ে "
        "EHAN EARN App খুলুন।"
    )


# ============================================================
# ADMIN
# ============================================================

def is_admin(user_id):

    return (
        ADMIN_ID != 0
        and
        user_id == ADMIN_ID
    )


async def adminstats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return


    conn = db()


    users =
        conn.execute(
            "SELECT COUNT(*) AS c FROM users"
        ).fetchone()["c"]


    points =
        conn.execute(
            "SELECT COALESCE(SUM(balance),0) AS c FROM users"
        ).fetchone()["c"]


    pending =
        conn.execute("""
            SELECT COUNT(*) AS c
            FROM withdrawals
            WHERE status='Pending'
        """).fetchone()["c"]


    conn.close()


    await update.message.reply_text(

        "👨‍💻 ADMIN STATS\n\n"

        f"👥 Users: {users}\n"
        f"💰 Points: {points:.2f}\n"
        f"💸 Pending withdrawals: {pending}"
    )


async def addtask(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return


    if len(
        context.args
    ) < 3:

        await update.message.reply_text(
            "/addtask REWARD TITLE DESCRIPTION"
        )

        return


    try:

        reward =
            float(
                context.args[0]
            )

    except Exception:

        await update.message.reply_text(
            "❌ Invalid reward"
        )

        return


    title =
        context.args[1]


    description =
        " ".join(
            context.args[2:]
        )


    conn = db()


    cursor =
        conn.execute("""
            INSERT INTO tasks
            (
                title,
                description,
                reward,
                active
            )
            VALUES
            (?, ?, ?, 1)
        """, (
            title,
            description,
            reward
        ))


    task_id =
        cursor.lastrowid


    conn.commit()

    conn.close()


    await update.message.reply_text(

        "✅ Task created\n\n"

        f"ID: {task_id}\n"
        f"Title: {title}\n"
        f"Reward: {reward}"
    )


async def pending(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return


    conn = db()


    rows =
        conn.execute("""
            SELECT *
            FROM withdrawals
            WHERE status='Pending'
            ORDER BY id DESC
            LIMIT 30
        """).fetchall()


    conn.close()


    if not rows:

        await update.message.reply_text(
            "💸 No pending withdrawals."
        )

        return


    text =
        "💸 PENDING WITHDRAWALS\n\n"


    for row in rows:

        text += (

            f"🆔 {row['id']}\n"
            f"👤 User: {row['user_id']}\n"
            f"💰 {row['amount']}\n"
            f"💳 {row['method']}\n"
            f"📱 {row['account']}\n\n"

            f"/approve {row['id']}\n"
            f"/reject {row['id']}\n\n"

        )


    await update.message.reply_text(
        text
    )


async def approve(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return


    if not context.args:

        await update.message.reply_text(
            "/approve ID"
        )

        return


    withdrawal_id =
        int(
            context.args[0]
        )


    conn = db()


    row =
        conn.execute("""
            SELECT *
            FROM withdrawals
            WHERE id=?
        """, (
            withdrawal_id,
        )).fetchone()


    if (
        not row
        or
        row["status"] != "Pending"
    ):

        conn.close()


        await update.message.reply_text(
            "❌ Invalid or processed request."
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
        "✅ Withdrawal approved."
    )


async def reject(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return


    if not context.args:

        await update.message.reply_text(
            "/reject ID"
        )

        return


    withdrawal_id =
        int(
            context.args[0]
        )


    conn = db()


    row =
        conn.execute("""
            SELECT *
            FROM withdrawals
            WHERE id=?
        """, (
            withdrawal_id,
        )).fetchone()


    if (
        not row
        or
        row["status"] != "Pending"
    ):

        conn.close()


        await update.message.reply_text(
            "❌ Invalid or processed request."
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
        "❌ Rejected and balance refunded."
    )


async def pendingtasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return


    conn = db()


    rows =
        conn.execute("""
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
            "📋 No pending tasks."
        )

        return


    text =
        "📋 PENDING TASKS\n\n"


    for row in rows:

        text += (

            f"🆔 {row['id']}\n"
            f"👤 {row['user_id']}\n"
            f"📌 {row['title']}\n"
            f"🎁 {row['reward']}\n"
            f"/approvetask {row['id']}\n\n"

        )


    await update.message.reply_text(
        text
    )


async def approvetask(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return


    if not context.args:

        await update.message.reply_text(
            "/approvetask ID"
        )

        return


    submission_id =
        int(
            context.args[0]
        )


    conn = db()


    row =
        conn.execute("""
            SELECT
                ts.*,
                t.reward
            FROM task_submissions ts
            JOIN tasks t
            ON t.id=ts.task_id
            WHERE ts.id=?
        """, (
            submission_id,
        )).fetchone()


    if (
        not row
        or
        row["status"] != "Pending"
    ):

        conn.close()


        await update.message.reply_text(
            "❌ Invalid submission."
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
        "✅ Task approved and reward added."
    )


async def adminhelp(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

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


# ============================================================
# COMMENT / MENTION
# ============================================================

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


    text =
        update.message.text.lower()


    me =
        await context.bot.get_me()


    mentioned =
        bool(
            me.username
            and
            "@"
            +
            me.username.lower()
            in text
        )


    replied =
        (
            update.message.reply_to_message
            and
            update.message.reply_to_message.from_user
            and
            update.message.reply_to_message.from_user.id
            ==
            me.id
        )


    if mentioned or replied:

        await update.message.reply_text(

            "🤖 EHAN EARN BOT\n\n"

            "আপনার message পেয়েছি। 😊\n\n"

            "🚀 App খুলতে /start দিন।"
        )


# ============================================================
# BOT POST INIT
# ============================================================

async def post_init(
    application
):

    commands = [

        BotCommand(
            "start",
            "Open EHAN EARN"
        ),

        BotCommand(
            "balance",
            "Check balance"
        ),

        BotCommand(
            "mining",
            "Mining"
        ),

        BotCommand(
            "daily",
            "Daily bonus"
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
            "My ID"
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


    # Telegram Menu Button
    # will open the Mini App.

    try:

        await application.bot.set_chat_menu_button(

            menu_button=
            MenuButtonWebApp(

                text="🚀 EHAN EARN",

                web_app=
                WebAppInfo(
                    url=WEBAPP_URL
                )

            )

        )

        print(
            "✅ Telegram Mini App menu button configured."
        )

    except Exception as e:

        print(
            "⚠️ Menu button setup:",
            e
        )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )


    init_db()


    threading.Thread(
        target=start_http_server,
        daemon=True
    ).start()


    application =
        (
            Application
            .builder()
            .token(TOKEN)
            .post_init(post_init)
            .build()
        )


    # USER COMMANDS

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "balance",
            balance_command
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
            "daily",
            daily
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
            tasks
        )
    )

    application.add_handler(
        CommandHandler(
            "done",
            done_task
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
            "games",
            games
        )
    )

    application.add_handler(
        CommandHandler(
            "guess",
            guess
        )
    )

    application.add_handler(
        CommandHandler(
            "leaderboard",
            leaderboard
        )
    )

    application.add_handler(
        CommandHandler(
            "withdraw
