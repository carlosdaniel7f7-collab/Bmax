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

# --- Telegram Bot Handlers (Original Features Intact) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_username = context.bot.username
    
    welcome_text = (
        "🤖 **Welcome to Bmax!**\n\n"
        "Heya! I'm Bmax — your advanced group and channel management bot here to help you secure, automate, and manage your communities as effectively as possible.\n\n"
        "⚡ **Core Capabilities:**\n"
        "• **Anti-Spam & Security:** Automatically block malicious links, floods, and unwanted bots.\n"
        "• **Channel Tools:** Streamline announcements and broadcast controls.\n"
        "• **Interactive Menus:** Seamless configuration for admins and members.\n\n"
        "📋 **Quick Navigation:** Choose an option below to get started or manage your settings."
    )
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Me to Your Group/Channel", url=f"https://t.me/{bot_username}?startgroup=true")],
        [InlineKeyboardButton("🛠 Admin Tools", callback_data="admin_panel"), InlineKeyboardButton("📜 Rules", callback_data="rules")],
        [InlineKeyboardButton("❓ Help & Commands", callback_data="help"), InlineKeyboardButton("ℹ️ About", callback_data="about")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "❓ **Bmax Command Reference Guide**\n\n"
        "Here are all available commands to control your chat:\n\n"
        "🔸 **General Commands:**\n"
        "• /start - Launch the main interactive dashboard\n"
        "• /help - Display this command index\n"
        "• /rules - View official community regulations\n\n"
        "🔹 **Admin & Management:**\n"
        "• Add me to your group or channel and promote me to **Admin** to enable automated filtering and moderation control."
    )
    keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rules_text = (
        "📜 **Official Community Guidelines**\n\n"
        "1. **No Spam or Unauthorized Ads:** Unsolicited link drops or advertisements result in instant removal.\n"
        "2. **Respect All Members:** Toxicity, harassment, or hate speech will not be tolerated.\n"
        "3. **Keep Content On-Topic:** Keep discussions aligned with the community's focus.\n"
        "4. **Admin Decisions Are Final:** Follow instructions given by channel staff."
    )
    keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(rules_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(rules_text, reply_markup=reply_markup, parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_text = (
        "🛠 **Admin Control Panel**\n\n"
        "To configure advanced settings for your group or channel:\n"
        "1. Ensure I am added as an **Administrator** with delete/ban permissions.\n"
        "2. Use management inline tools to govern your traffic securely."
    )
    keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(admin_text, reply_markup=reply_markup, parse_mode="Markdown")

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    about_text = (
        "ℹ️ **About Bmax Bot**\n\n"
        "Bmax is built to rival top-tier management utilities, offering robust cloud hosting, instant response handling, and clean modular expansion for high-traffic channels."
    )
    keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="start_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(about_text, reply_markup=reply_markup, parse_mode="Markdown")

# --- ROSE-STYLE WELCOME GREETING & AUTO-DESTRUCT TASK ---
async def delete_welcome_message(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    message_id = job_data["message_id"]
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.error(f"Failed to auto-delete welcome message: {e}")

# --- COMPLETE SECURITY GUARD (WELCOME BUTTON, PROFANITY, LINKS, & STRICT MEDIA FILTER) ---
async def security_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    message = update.message
    
    # 1. Rose-Style Welcome Greeter with Interactive Verify Button
    if message.new_chat_members:
        for member in message.new_chat_members:
            if member.id == context.bot.id:
                continue
            
            welcome_text = f"Hey {member.first_name}, welcome to the group! Please verify your account to get started."
            keyboard = [[InlineKeyboardButton("✅ Verify You Are Human", callback_data=f"verify_{member.id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            sent_msg = await message.reply_text(welcome_text, reply_markup=reply_markup)
            
            # Automatically delete the welcome greeting after 5 seconds
            context.job_queue.run_once(
                delete_welcome_message, 
                5.0, 
                data={"chat_id": message.chat_id, "message_id": sent_msg.message_id}
            )
        return

    # Skip if sent by the bot itself
    if message.from_user and message.from_user.id == context.bot.id:
        return

    text_content = message.text or message.caption or ""
    text_lower = text_content.lower()

    # 2. Broad 18+ / NSFW & Adult Content Detection
    adult_patterns = [
        "18\\+", "nsfw", "porn", "porno", "sex", "xxx", "adult", 
        "nude", "naked", "hentai", "camgirl", "onlyfans", "erotic", "stripper"
    ]
    
    # 3. Comprehensive Profanity & Slur Bank
    profanity_patterns = [
        "fuck", "f+ck", "f*ck", "fuc", "fck", "bullshit", "bullsh*t", 
        "shit", "sh*t", "asshole", "ass", "bitch", "bastard", "dick", 
        "cunt", "motherfucker", "cock", "pussy", "slut", "whore", 
        "stfu", "kys", "motherf*cker"
    ]

    all_restricted_words = adult_patterns + profanity_patterns
    
    is_profane_or_adult = any(re.search(rf"\b{word}\b", text_lower) for word in all_restricted_words) or any(word in text_lower for word in ["sex", "porn", "xxx", "nsfw", "fuck", "shit", "bitch"])

    # 4. Unauthorized Links & Telegram Invite Blocker
    has_unauthorized_link = ("http://" in text_lower or "https://" in text_lower or "t.me/" in text_lower or "t.me/+" in text_lower or "joinchat" in text_lower)

    # 5. Strict Media Filter (Instantly deletes all GIFs, Animations, Videos, and Photos)
    is_unwanted_media = bool(message.animation or message.video or message.photo)

    # Trigger deletion if any rule is violated
    if is_profane_or_adult or has_unauthorized_link or is_unwanted_media:
        try:
            await message.delete()
            logger.info("Security guard successfully intercepted and removed a restricted message or media.")
        except Exception as e:
            logger.error(f"Failed to delete message. Ensure bot has Delete Messages admin rights: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("verify_"):
        user_id_str = query.data.split("_")[1]
        # Check if the person clicking the button is the actual user who joined
        if query.from_user.id == int(user_id_str):
            await query.answer("✅ Successfully verified!", show_alert=True)
            try:
                await query.message.delete()
            except Exception:
                pass
        else:
            await query.answer("❌ This verification button is not for you!", show_alert=True)
        return

    if query.data == "rules":
        await rules_command(update, context)
    elif query.data == "help":
        await help_command(update, context)
    elif query.data == "admin_panel":
        await admin_panel(update, context)
    elif query.data == "about":
        await about_command(update, context)
    elif query.data == "start_menu":
        await start(update, context)

def main() -> None:
    keep_alive()

    TOKEN = "8958433337:AAGivMvCxEbjdlX4g5tAtHlacKImdlSqUy0"

    application = Application.builder().token(TOKEN).build()

    # Original Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("rules", rules_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Comprehensive Protection Handler
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, security_guard))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
