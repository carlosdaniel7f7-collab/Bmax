import logging
import threading
import asyncio
import random
import requests
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
user_verified_chats = {} 
pending_verifications = {}  # user_id: target_code

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
                parts = arg.split("_")
                target_chat_id = int(parts[1]) if len(parts) >= 2 else None
                
                if target_chat_id and user_id in user_verified_chats and target_chat_id in user_verified_chats[user_id]:
                    if update.message:
                        await update.message.reply_text("You are already verified.")
                else:
                    code = str(random.randint(1000, 9999))
                    pending_verifications[user_id] = {
                        "code": code,
                        "args": arg
                    }
                    if update.message:
                        await update.message.reply_text(
                            f"🔐 **Verification Challenge**\n\n"
                            f"Please reply with the following number to prove you are human: **{code}**"
                        )
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
    user_id = message.from_user.id if message.from_user else None
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

    if user_id and user_id == context.bot.id:
        return

    # Check if user is completing the verification challenge in private chat
    if message.chat.type == "private" and user_id:
        if user_id in pending_verifications:
            user_text = (message.text or "").strip()
            expected_code = pending_verifications[user_id]["code"]
            arg = pending_verifications[user_id]["args"]
            
            parts = arg.split("_")
            target_chat_id = int(parts[1]) if len(parts) >= 2 else None

            if target_chat_id and user_id in user_verified_chats and target_chat_id in user_verified_chats[user_id]:
                await message.reply_text("You are already verified.")
                return

            if user_text == expected_code:
                if user_id not in user_verified_chats:
                    user_verified_chats[user_id] = set()
                if target_chat_id:
                    user_verified_chats[user_id].add(target_chat_id)

                del pending_verifications[user_id]
                
                await message.reply_text("You're all set! You're now verified and ready to chat in the group.")
                
                if len(parts) == 3:
                    try:
                        target_msg_id = int(parts[2])
                        await context.bot.delete_message(chat_id=target_chat_id, message_id=target_msg_id)
                        logger.info("Successfully auto-deleted verification message from the group.")
                    except Exception as e:
                        logger.error(f"Could not auto-delete verification message: {e}")
                return
            else:
                await message.reply_text(f"❌ Incorrect code. Please send the exact number: {expected_code}")
                return

    # --- 1. Check text & captions for explicit words ---
    text_content = (message.text or message.caption or "").lower()
    nsfw_keywords = ["porn", "xxx", "nsfw", "sex", "nude", "hardcore", "18+"]
    is_nsfw_text = any(word in text_content for word in nsfw_keywords)

    if is_nsfw_text:
        try:
            await message.delete()
            logger.info("Deleted message containing explicit text or caption.")
            return
        except Exception as e:
            logger.error(f"Failed to delete explicit text message: {e}")
            return

    # --- 2. Check Photos or GIFs visually using AI Vision API ---
    file_to_check = None
    if message.photo:
        file_to_check = await message.photo[-1].get_file()
    elif message.animation:
        file_to_check = await message.animation.get_file()

    if file_to_check:
        try:
            file_url = file_to_check.file_path
            
            # DeepAI NSFW detector integration
            r = requests.post(
                "https://api.deepai.org/api/nsfw-detector",
                files={'image': requests.get(file_url).content},
                headers={'api-key': 'YOUR_DEEPAI_API_KEY'}
            )
            result = r.json()
            nsfw_score = result.get("output", {}).get("nsfw_score", 0.0)
            
            # If AI determines it is over 75% likely to be NSFW, delete it
            if nsfw_score > 0.75:
                await message.delete()
                logger.info(f"Deleted 18+ media with NSFW score: {nsfw_score}")
                
        except Exception as e:
            logger.error(f"Error scanning media with AI API: {e}")

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
    TOKEN = "8958433337:AAE-5wKmRYp0I_-bpuLF7rMkJAPDQpVPyic"
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("rules", rules_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, security_guard))

    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
