import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ChatMemberHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# /start command handler with invite button
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot.username
    add_link = f"https://t.me/{bot_username}?startgroup=true&admin=delete_messages+invite_users"
    
    keyboard = [
        [InlineKeyboardButton("🤖 Add me to your Channel/Group", url=add_link)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "BEEP BOOP! 🤖 Hello there!\n\n"
        "I am your automated security guard bot for @Anime7p7.\n"
        "I automatically delete unauthorized links, 18+ spam, and profanity to keep your community clean.\n\n"
        "Click the button below to add me to your own group or channel!"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

# /help command handler
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📜 **Bot Command Menu**\n\n"
        "/start - Launch the bot and get the invite link\n"
        "/help - View this command list\n"
        "/admin - Check bot security status\n\n"
        "🛡️ **Active Protections:**\n"
        "• Anti-Spam (Blocks links & t.me invites)\n"
        "• NSFW Filter (Blocks adult terms)\n"
        "• Profanity Filter (Blocks bad words)\n"
        "• Welcome Greeter (Welcomes new members)"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# /admin command handler
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ Security systems are fully operational and guarding @Anime7p7 24/7!")

# Welcome new members when they join
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if result:
        new_member = result.new_chat_member
        if new_member.status == "member":
            user_name = new_member.user.first_name
            chat_name = update.effective_chat.title
            greeting = f"Welcome to {chat_name}, {user_name}! Glad to have you here. Please follow the rules and enjoy your stay! 🎉"
            await context.bot.send_message(chat_id=update.effective_chat.id, text=greeting)

# Spam, NSFW, and Profanity message cleaner
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.lower()

    spam_triggers = ["http://", "https://", "t.me/", "telegram.me/", "joinchat"]
    nsfw_triggers = ["18+", "nsfw", "porn", "xxx"]
    profanity_triggers = ["fuck", "shit", "bitch", "asshole"] 

    is_spam = any(trigger in user_text for trigger in spam_triggers)
    is_nsfw = any(word in user_text for word in nsfw_triggers)
    is_profane = any(bad_word in user_text for bad_word in profanity_triggers)

    if is_spam or is_nsfw or is_profane:
        try:
            await update.message.delete()
            print("BEEP BOOP! 🤖 Target acquired. Unauthorized link, NSFW content, or profanity terminated successfully.")
        except Exception as e:
            print(f"BEEP BOOP ERROR: Could not delete message -> {e}")

def main():
    application = ApplicationBuilder().token("8958433337:AAHzDhBPHVT2v19ng1TcCRAHzTIbXZGTP18").build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("BEEP BOOP... Rose-style features and anti-spam robot is online and guarding @Anime7p7!")
    application.run_polling()

if __name__ == '__main__':
    main()
