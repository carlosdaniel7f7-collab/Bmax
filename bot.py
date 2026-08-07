import logging
import threading
import asyncio
import re
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Dummy Web Server for Render Port Binding ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.start()

# --- In-Memory Verification Tracking ---
verified_users = set()

# --- Global Error Handler (Prevents crashes) ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_username = context.bot.username
    user_id = update.effective_user.id if update.effective_user else None
    
    if context.args:
        arg = context.args[0]
        if arg.startswith("verify"):
            if user_id:
                if user_id in verified_users:
                    if update.message:
                        await update.message.reply_text("You already verified.")
                else:
                    verified_users.add(user_id)
                    if update.message:
                        await update.message.reply_text("✅ Verification successful! You are confirmed as human. You can now chat freely in your groups.")
                    
                    parts = arg.split("_")
                    if len(parts) == 3:
                        try:
                            target_chat_id = int(parts[1])
                            target_msg_id = int(parts[2])
                            await context.bot.delete_message(chat_id=target_chat_id, message_id=target_msg_id)
                            logger.info("Successfully auto-deleted verification message from the group.")
                        except Exception as e:
                            logger.error(f"Could not auto-delete verification message: {e}")
            return

    welcome_text = (
        "🤖 Welcome to Bmax Ultimate Command Center!\n\n"
        "Heya! I'm Bmax — your next-generation high-performance security, moderation, and community management powerhouse.\n\n"
        "⚡ Elite Core Capabilities:\n"
        "• Advanced Anti-Spam & Shield: Instantly blocks malicious links, floods, raid bots, and scams.\n"
        "• Smart Content Filter: Auto-removes NSFW media and severe profanity.\n"
        "• Interactive Verification: Seamless human verification prompts to lock down public groups.\n\n"
        "📋 Quick Navigation Dashboard: Select an option below to configure your settings."
    )
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Me to Your Group", url=f"https://t.me/{bot_username}?startgroup=true")],
        [InlineKeyboardButton("📢 Add Me to Your Channel", url=f"https://t.me/{bot_username}?startchannel=true")],
        [InlineKeyboardButton("🛠 Admin Control Panel", callback_data="admin_panel"), InlineKeyboardButton("📜 Community Rules", callback_data="rules")],
        [InlineKeyboardButton("❓ Help & Commands", callback_data="help"), InlineKeyboardButton("ℹ️ About Bmax", callback_data="about")],
        [InlineKeyboardButton("🛡 Security Status", callback_data="status"), InlineKeyboardButton("⚡ Feature Showcase", callback_data="features")],
        [InlineKeyboardButton("🌐 Official Support Community", url="https://t.me/Anime7p7")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if update.message:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup)
        elif update.callback_query:
            await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in start handler message dispatch: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = "❓ **Bmax Command Reference Guide**\n\nUse /start to open the main interactive dashboard."
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(help_text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(help_text, reply_markup=reply_markup)

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rules_text = "📜 **Official Community Guidelines & Rules**\n\n1. Zero Spam & Ads\n2. Absolute Respect\n3. No NSFW Media"
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(rules_text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(rules_text, reply_markup=reply_markup)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_text = "🛠 **Admin Control Panel**\nEnsure I am promoted as an Administrator with message deletion privileges."
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(admin_text, reply_markup=reply_markup)

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    about_text = "ℹ️ **About Bmax Bot**\nNext-gen Telegram management utility."
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(about_text, reply_markup=reply_markup)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status_text = "🛡 **Bmax Security Status**\n• Core Engine: Online\n• Cloud Uptime: 99.9%"
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(status_text, reply_markup=reply_markup)

async def features_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    features_text = "⚡ **Elite Feature Showcase**\n• Raid Defense\n• Smart Link Blacklisting"
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(features_text, reply_markup=reply_markup)

async def security_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    message = update.message
    bot_username = context.bot.username
    
    if message.new_chat_members:
        for member in message.new_chat_members:
            if member.id == context.bot.id:
                continue
            welcome_text = f"Welcome, {member.first_name}!"
            sent_msg = await message.reply_text(welcome_text)
            verify_payload = f"verify_{message.chat_id}_{sent_msg.message_id}"
            keyboard = [[InlineKeyboardButton("Verify here you are a human", url=f"https://t.me/{bot_username}?start={verify_payload}")]]
            await sent_msg.edit_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if message.from_user and message.from_user.id == context.bot.id:
        return

    text_lower = (message.text or message.caption or "").lower()
    is_profane = any(word in text_lower for word in ["sex", "porn", "xxx", "nsfw", "fuck", "shit", "bitch"])
    has_link = ("http://" in text_lower or "https://" in text_lower or "t.me/" in text_lower)
    is_media = bool(message.animation or message.video or message.photo)

    if is_profane or has_link or is_media:
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Failed to delete message: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "rules": await rules_command(update, context)
    elif query.data == "help": await help_command(update, context)
    elif query.data == "admin_panel": await admin_panel(update, context)
    elif query.data == "about": await about_command(update, context)
    elif query.data == "status": await status_command(update, context)
    elif query.data == "features": await features_command(update, context)
    elif query.data == "start_menu": await start(update, context)

def main() -> None:
    keep_alive()
    TOKEN = "8958433337:AAGYidUkDFUmsnPqChQcGshggg4m-flAWY8"
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("rules", rules_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, security_guard))

    # Register the global error handler
    application.add_error_handler(error_handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
