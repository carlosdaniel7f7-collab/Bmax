import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.lower()

    spam_triggers = ["http://", "https://", "www.", "t.me/", "joinchat", "@", "channel", "subscribe"]
    nsfw_triggers = ["18+", "nsfw", "porn", "adult", "sex", "nude"]

    is_spam = any(trigger in user_text for trigger in spam_triggers)
    is_nsfw = any(word in user_text for word in nsfw_triggers)

    if is_spam or is_nsfw:
        try:
            await update.message.delete()
            print("BEEP BOOP! 🤖 Target acquired. Unauthorized link or 18+ spam terminated successfully!")
        except Exception as e:
            print(f"BEEP BOOP ERROR: Could not delete message -> {e}")

def main():
    application = ApplicationBuilder().token("8958433337:AAHNVafXsRw9SlscQzFT1PSKYp1D-GmrVFITap inside the large box below that says "Enter file contents here", and paste your Python script right there.").build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("BEEP BOOP... Anti-spam robot is online and guarding @Anime7p7!")
    application.run_polling()


if __name__ == '__main__':
    main()
