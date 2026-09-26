import os
import threading
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "users.db"


# =========================
# DATABASE
# =========================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
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
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user.id,)
    )

    exists = cursor.fetchone()

    if not exists:
        cursor.execute(
            """
            INSERT INTO users
            (user_id, username, first_name, balance, referred_by)
            VALUES (?, ?, ?, 0, ?)
            """,
            (
                user.id,
                user.username or "",
                user.first_name or "",
                referred_by
            )
        )

        if referred_by and referred_by != user.id:
            cursor.execute(
                """
                UPDATE users
                SET referral_count = referral_count + 1
                WHERE user_id = ?
                """,
                (referred_by,)
            )

    conn.commit()
    conn.close()


def get_balance(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,)
    )

    result = cursor.fetchone()
    conn.close()

    return result[0] if result else 0


def get_referral_count(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT referral_count FROM users WHERE user_id = ?",
        (user_id,)
    )

    result = cursor.fetchone()
    conn.close()

    return result[0] if result else 0


# =========================
# WEB SERVER
# =========================

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


# =========================
# START
# =========================

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


# =========================
# BALANCE
# =========================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):

    add_user(update.effective_user)

    user_balance = get_balance(update.effective_user.id)

    await update.message.reply_text(
        f"💰 আপনার Balance: {user_balance:.2f} Points"
    )


# =========================
# REFERRAL
# =========================

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):

    add_user(update.effective_user)

    user_id = update.effective_user.id
    count = get_referral_count(user_id)

    bot_username = context.bot.username

    referral_link = f"https://t.me/{bot_username}?start={user_id}"

    await update.message.reply_text(
        "👥 আপনার Referral System\n\n"
        f"🔗 আপনার Referral Link:\n{referral_link}\n\n"
        f"👤 Total Referrals: {count}\n\n"
        "আপনার Referral Link অন্যদের সাথে শেয়ার করুন।"
    )


# =================
