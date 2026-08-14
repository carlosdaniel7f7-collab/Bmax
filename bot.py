import os
import re
import logging
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bmax")

# ============================================================
# ENVIRONMENT
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

# ============================================================
# BLOCKED WORDS & TERMS
# ============================================================

BLOCKED_WORDS = {
    "porn", "porno", "pornography", "sex", "sexual", "sexy",
    "nude", "nudes", "nudity", "naked", "nsfw", "xxx", "hentai",
    "anal", "vagina", "penis", "genitals", "pussy", "dick", "cock",
    "boobs", "tits", "erotic", "explicit", "lewd", "onlyfans",
    "sexcam", "sexchat"
}

# ============================================================
# FLASK KEEP ALIVE (FOR RENDER)
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bmax Fast-Shield Bot is alive and running!"

@app.route("/health")
def health():
    return {"status": "ok", "mode": "instant-rules"}

def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()

# ============================================================
# SECURITY UTILITIES
# ============================================================

async def delete_message_safely(message, reason=""):
    try:
        await message.delete()
        logger.warning("INSTANT REMOVED: %s", reason)
        return True
    except Exception as e:
        logger.error("Failed to delete message: %s", e)
        return False

def contains_blocked_word(text: str):
    if not text:
        return None
    lowered = text.lower()
    for word in BLOCKED_WORDS:
        pattern = rf"(?<!\w){re.escape(word)}(?!\w)"
        if re.search(pattern, lowered):
            return word
    return None

# ============================================================
# CORE SECURITY GUARD (ZERO LAG)
# ============================================================

async def security_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    message = update.message

    if message.from_user and message.from_user.id == context.bot.id:
        return

    if message.chat.type not in ("group", "supergroup"):
        return

    # 1. Text & Caption Analysis
    text_content = message.text or message.caption or ""
    blocked_word = contains_blocked_word(text_content)
    if blocked_word:
        await delete_message_safely(message, f"blocked word: {blocked_word}")
        return

    # 2. Instant Media Filename & Document Screening
    if message.video:
        file_name = (message.video.file_name or "").lower()
        if any(w in file_name for w in ["porn", "sex", "xxx", "nsfw", "adult"]):
            await delete_message_safely(message, "explicit video file name")
            return

    if message.document:
        file_name = (message.document.file_name or "").lower()
        mime_type = (message.document.mime_type or "").lower()
        if any(w in file_name for w in ["porn", "sex", "xxx", "nsfw", "adult"]) or "video" in mime_type:
            if any(w in file_name for w in ["porn", "sex", "xxx", "nsfw", "adult"]):
                await delete_message_safely(message, "explicit document payload")
                return

# ============================================================
# COMMAND HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot.username
    welcome_text = (
        "🤖 **Bmax Lightning Shield Active**\n\n"
        "Heya! I'm guarding this chat with zero-lag instant text and file filtering.\n\n"
        "⚡ All explicit text inputs and flagged items are wiped out immediately."
    )
    keyboard = [
        [InlineKeyboardButton("➕ Add Me to Your Group", url=f"https://t.me/{bot_username}?startgroup=true")],
        [InlineKeyboardButton("🌐 Official Community", url="https://t.me/Anime7p7")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=markup, parse_mode="Markdown")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update:", exc_info=context.error)

# ============================================================
# MAIN ENTRYPOINT
# ============================================================

def main():
    logger.info("Starting Bmax Fast-Shield...")
    keep_alive()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, security_guard))
    application.add_error_handler(error_handler)

    logger.info("Bmax is polling updates...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
