import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text("💰 আপনার Balance: 0")

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌍 International Quiz শীঘ্রই চালু হবে।")

async def mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⛏️ Virtual Mining শুরু করার ব্যবস্থা করা হচ্ছে।")

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 বর্তমানে কোনো Task নেই।")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👥 আপনার Referral system শীঘ্রই চালু হবে।")

async def games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎮 Games শীঘ্রই চালু হবে।")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💸 Withdrawal system শীঘ্রই চালু হবে।")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏆 Leaderboard শীঘ্রই চালু হবে।")

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📜 BOT RULES\n\n"
        "• একাধিক fake account ব্যবহার করবেন না।\n"
        "• প্রতারণামূলক কাজ করা যাবে না।\n"
        "• Withdrawal-এর আগে প্রয়োজনীয় শর্ত পূরণ করতে হবে।"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 Help\n\n"
        "যেকোনো সমস্যায় Admin-এর সাথে যোগাযোগ করুন।"
    )

def main():
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
