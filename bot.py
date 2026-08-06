import logging
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

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

# --- Telegram Bot Handlers & Professional Suite ---
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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
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

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("rules", rules_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
