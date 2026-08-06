import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ChatMemberHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# /start command handler (works in both private DMs and groups)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot.username
    add_link = f"https://t.me/{bot_username}?startgroup=true&admin=delete_messages+invite_users"
    
    keyboard = [
        [InlineKeyboardButton("🤖 Add me to your Channel/Group", url=add_link)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "Heya! I'm Bmax - an automated security guard bot here to help protect your groups and channels from spam, links, 18+ media, stickers, and explicit content as effectively as possible.\n\n"
        "Press START or click the button below to add me to your group!"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

# /help command handler
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📜 **Bot Command Menu**\n\n"
        "/start - Launch the bot and get the invite link\n"
        "/help - View this command list\n"
        "/admin - Check bot security status\n\n"
        "🛡️ **Active Protections:**\n"
        "• Anti-Spam (Blocks links & t.me invites)\n"
        "• 18+ Media Filter (Blocks adult GIFs, stickers, photos & videos)\n"
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

# Comprehensive cleaner for Text, GIFs, Stickers, Photos, and Videos in groups/channels
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    message = update.message
    user_text = ""

    if message.text:
        user_text = message.text.lower()
    elif message.caption:
        user_text = message.caption.lower()

    spam_triggers = ["http://", "https://", "t.me/", "telegram.me/", "joinchat"]
    nsfw_triggers = ["18+", "nsfw", "porn", "xxx", "sex", "hentai", "adult"]
    profanity_triggers = ["fuck", "shit", "bitch", "asshole"] 

    is_spam = any(trigger in user_text for trigger in spam_triggers)
    is_nsfw = any(word in user_text for word in nsfw_triggers)
    is_profane = any(bad_word in user_text for bad_word in profanity_triggers)

    is_restricted_media = message.sticker or message.animation

    if is_spam or is_nsfw or is_profane or is_restricted_media:
        try:
            await message.delete()
            print("BEEP BOOP! 🤖 Target acquired. Unauthorized link, 18+ media/text, sticker, or profanity terminated successfully.")
        except Exception as e:
            print(f"BEEP BOOP ERROR: Could not delete message -> {e}")

# Respond to private chat messages so users aren't left on read when they DM the bot
async def private_chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        bot_username = context.bot.username
        add_link = f"https://t.me/{bot_username}?startgroup=true&admin=delete_messages+invite_users"
        
        keyboard = [
            [InlineKeyboardButton("🤖 Add me to your Channel/Group", url=add_link)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Heya! I'm Bmax - an automated security guard bot here to help protect your groups and channels from spam, links, 18+ media, stickers, and explicit content as effectively as possible.\n\n"
            "Click the button below to add me to your group!",
            reply_markup=reply_markup
        )

def main():
    application = ApplicationBuilder().token("8958433337:AAGivMvCxEbjdlX4g5tAtHlacKImdlSqUy0").build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))
    
    # Handle private DM messages so the bot talks back instead of staying blank
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & (~filters.COMMAND), private_chat_handler))
    
    # Listen to group content updates (text, photos, videos, stickers, animations)
    application.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_message))
    
    print("BEEP BOOP... Enhanced anti-spam and NSFW media robot is online and guarding @Anime7p7!")
    application.run_polling()

if __name__ == '__main__':
    main()
