import logging
import threading
import os
import re
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "8958433337:AAGYidUkDFUmsnPqChQcGshggg4m-flAWY8"
PORT = int(os.environ.get("PORT", 10000))
# Replace this with your actual Render web service URL once deployed (e.g., https://your-app-name.onrender.com)
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

app = Flask(__name__)
verified_users = set()

# Initialize Telegram Application
telegram_app = Application.builder().token(TOKEN).build()

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
                        await update.message.reply_text("✅ **Verification successful!** You are confirmed as human. You can now chat freely in your groups.")
                    
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
        "🤖 **Welcome to Bmax Ultimate Command Center!**\n\n"
        "Heya! I'm Bmax — your next-generation high-performance security, moderation, and community management powerhouse.\n\n"
        "⚡ **Elite Core Capabilities:**\n"
        "• **Advanced Anti-Spam & Shield:** Instantly blocks malicious links, floods, raid bots, and unauthorized scams.\n"
        "• **Smart Content Filter:** Auto-removes 18+/NSFW media and severe profanity.\n"
        "• **Interactive Verification:** Seamless human verification prompts to lock down public groups.\n\n"
        "📋 **Quick Navigation Dashboard:** Select an option below to configure your settings."
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

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = "❓ **Bmax Command Reference Guide**\n\nUse /start to open the main interactive dashboard."
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rules_text = "📜 **Official Community Guidelines & Rules**\n\n1. Zero Spam & Ads\n2. Absolute Respect\n3. No NSFW Media"
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(rules_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(rules_text, reply_markup=reply_markup, parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_text = "🛠 **Admin Control Panel**\nEnsure I am promoted as an Administrator with message deletion privileges."
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(admin_text, reply_markup=reply_markup, parse_mode="Markdown")

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    about_text = "ℹ️ **About Bmax Bot**\nNext-gen Telegram management utility."
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(about_text, reply_markup=reply_markup, parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status_text = "🛡 **Bmax Security Status**\n• Core Engine: Online (Webhook Mode)\n• Cloud Uptime: 99.9%"
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(status_text, reply_markup=reply_markup, parse_mode="Markdown")

async def features_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    features_text = "⚡ **Elite Feature Showcase**\n• Raid Defense\n• Smart Link Blacklisting"
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(features_text, reply_markup=reply_markup, parse_mode="Markdown")

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

# Register handlers
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("rules", rules_command))
telegram_app.add_handler(CallbackQueryHandler(button_handler))
telegram_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, security_guard))

@app.route('/')
def index():
    return "Bmax Webhook Bot is running smoothly!"

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    json_data = request.get_json(force=True)
    update = Update.de_json(json_data, telegram_app.bot)
    
    async def process():
        await telegram_app.initialize()
        await telegram_app.process_update(update)

    threading.Thread(target=lambda: asyncio.run(process())).start()
    return 'OK', 200

def set_bot_webhook():
    if WEBHOOK_URL:
        full_url = f"{WEBHOOK_URL}/{TOKEN}"
        import requests
        requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={full_url}")
        logger.info(f"Webhook set to: {full_url}")

if __name__ == "__main__":
    set_bot_webhook()
    app.run(host='0.0.0.0', port=PORT)
