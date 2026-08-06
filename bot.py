import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# /start command handler (Acts like Rose with an invite button)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot.username
    # This creates a direct link to add the bot with admin rights pre-selected for channels/groups
    add_link = f"https://t.me/{bot_username}?startgroup=true&admin=delete_messages+invite_users"
    
    keyboard = [
        [InlineKeyboardButton("🤖 Add me to your Channel/Group", url=add_link)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "BEEP BOOP! 🤖 Hello there!\n\n"
        "I am your automated security guard bot for @Anime7p7.\n"
        "I automatically delete unauthorized links and 18+ spam to keep your community clean.\n\n"
        "Click the button below to add me to your own group or channel!"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

# Spam & NSFW message cleaner
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.lower()

    spam_triggers = ["http://", "https://", "t.me/", "telegram.me/", "joinchat"]
    nsfw_triggers = ["18+", "nsfw", "porn", "xxx"]

    is_spam = any(trigger in user_text for trigger in spam_triggers)
    is_nsfw = any(word in user_text for word in nsfw_triggers)

    if is_spam or is_nsfw:
        try:
            await update.message.delete()
            print("BEEP BOOP! 🤖 Target acquired. Unauthorized link or 18+ spam terminated successfully.")
        except Exception as e:
            print(f"BEEP BOOP ERROR: Could not delete message -> {e}")

def main():
    # Your current bot token
    application = ApplicationBuilder().token("8958433337:AAHzDhBPHVT2v19ng1TcCRAHzTIbXZGTP18").build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("BEEP BOOP... Anti-spam robot with /start commands is online and guarding @Anime7p7!")
    application.run_polling()

if __name__ == '__main__':
    main()
