import os
import re
import io
import logging
import threading
import asyncio
import random
import requests

from flask import Flask
from PIL import Image, UnidentifiedImageError

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPAI_API_KEY = os.getenv("DEEPAI_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

# ============================================================
# RENDER KEEP-ALIVE WEB SERVER
# ============================================================

app = Flask("")


@app.route("/")
def home():
    return "Bot is alive and running!"


def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    thread = threading.Thread(target=run_flask, daemon=True)
    thread.start()


# ============================================================
# VERIFICATION STORAGE
# ============================================================

user_verified_chats = {}
pending_verifications = {}


# ============================================================
# UNWANTED / PROFANITY WORD FILTER
# ============================================================

# Add or remove words from this list whenever you want.
BLOCKED_WORDS = {
    "fuck",
    "fucking",
    "fucked",
    "fucker",
    "fuckers",
    "shit",
    "shitty",
    "bullshit",
    "bitch",
    "bitches",
    "asshole",
    "assholes",
    "dickhead",
    "bastard",
    "motherfucker",
    "motherfuckers",
}

# Words that are commonly used to disguise profanity.
# Keep this list conservative so normal words aren't accidentally deleted.
DISGUISED_WORDS = {
    "f1uck": "fuck",
    "f4ck": "fuck",
    "sh1t": "shit",
    "b1tch": "bitch",
    "a55hole": "asshole",
}


def normalize_text(text: str) -> str:
    """
    Normalize text to make simple obfuscation easier to detect.

    Example:
        F.U.C.K -> fuck
        f u c k -> fuck
        Sh1t    -> shit
    """

    text = text.lower()

    # Replace common leetspeak characters.
    replacements = {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "@": "a",
        "$": "s",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # Remove spaces and punctuation between letters.
    compact = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)

    return compact


def contains_blocked_word(text: str):
    """
    Returns the blocked word if one is detected.
    Otherwise returns None.
    """

    if not text:
        return None

    lowered = text.lower()

    # Normal word-boundary matching.
    for word in BLOCKED_WORDS:
        pattern = rf"(?<!\w){re.escape(word)}(?!\w)"

        if re.search(pattern, lowered):
            return word

    # Check common disguised versions.
    for disguised, original in DISGUISED_WORDS.items():
        if disguised in lowered:
            return original

    # Check compacted text for punctuation/spacing tricks.
    normalized = normalize_text(text)

    for word in BLOCKED_WORDS:
        if word in normalized:
            return word

    return None


# ============================================================
# NSFW DETECTOR
# ============================================================

def deepai_check_image(image_bytes: bytes):
    """
    Sends an image to DeepAI.

    Returns:
        NSFW score as float, or None if scanning failed.
    """

    if not DEEPAI_API_KEY:
        logger.warning("DEEPAI_API_KEY is not configured.")
        return None

    try:
        response = requests.post(
            "https://api.deepai.org/api/nsfw-detector",
            files={
                "image": (
                    "image.jpg",
                    image_bytes,
                    "image/jpeg"
                )
            },
            headers={
                "api-key": DEEPAI_API_KEY
            },
            timeout=30
        )

        response.raise_for_status()

        result = response.json()

        # DeepAI response structure may vary.
        output = result.get("output", {})

        score = output.get("nsfw_score")

        if score is None:
            # Some API responses may return the value differently.
            score = result.get("nsfw_score")

        if score is None:
            return None

        return float(score)

    except Exception as e:
        logger.error(f"DeepAI scanning error: {e}")
        return None


async def scan_image(image_bytes: bytes):
    """
    Runs the blocking HTTP request outside the asyncio event loop.
    """

    return await asyncio.to_thread(
        deepai_check_image,
        image_bytes
    )


# ============================================================
# PHOTO SCANNER
# ============================================================

async def check_photo(message):
    """
    Download and scan a Telegram photo.
    """

    try:
        telegram_file = await message.photo[-1].get_file()

        image_bytes = await telegram_file.download_as_bytearray()

        score = await scan_image(bytes(image_bytes))

        if score is None:
            return False, None

        logger.info(
            f"Photo NSFW score: {score:.3f}"
        )

        return score >= 0.75, score

    except Exception as e:
        logger.error(f"Photo scanning failed: {e}")
        return False, None


# ============================================================
# GIF / ANIMATION SCANNER
# ============================================================

def extract_gif_frames(gif_bytes: bytes, max_frames=3):
    """
    Extract a few frames from a GIF.

    We don't scan every frame because that would be unnecessarily
    expensive and slow.
    """

    frames = []

    try:
        image = Image.open(io.BytesIO(gif_bytes))

        frame_count = getattr(image, "n_frames", 1)

        if frame_count <= 1:
            positions = [0]
        else:
            positions = [
                0,
                frame_count // 2,
                frame_count - 1
            ]

        positions = positions[:max_frames]

        for position in positions:
            try:
                image.seek(position)

                frame = image.convert("RGB")

                output = io.BytesIO()
                frame.save(
                    output,
                    format="JPEG",
                    quality=85
                )

                frames.append(output.getvalue())

            except Exception as e:
                logger.warning(
                    f"Could not extract GIF frame {position}: {e}"
                )

    except (UnidentifiedImageError, Exception) as e:
        logger.error(f"GIF processing failed: {e}")

    return frames


async def check_animation(message):
    """
    Scan a few frames of a GIF/animation.

    Normal reaction GIFs are allowed unless the detector gives
    a high NSFW score.
    """

    try:
        telegram_file = await message.animation.get_file()

        gif_bytes = await telegram_file.download_as_bytearray()

        frames = extract_gif_frames(
            bytes(gif_bytes),
            max_frames=3
        )

        if not frames:
            return False, None

        highest_score = 0.0

        for frame in frames:

            score = await scan_image(frame)

            if score is None:
                continue

            highest_score = max(
                highest_score,
                score
            )

        logger.info(
            f"GIF highest NSFW score: {highest_score:.3f}"
        )

        return highest_score >= 0.75, highest_score

    except Exception as e:
        logger.error(
            f"GIF scanning failed: {e}"
        )

        return False, None


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    logger.error(
        msg="Exception while handling an update:",
        exc_info=context.error
    )


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    bot_username = context.bot.username

    user_id = (
        update.effective_user.id
        if update.effective_user
        else None
    )

    # --------------------------------------------------------
    # VERIFICATION LINK
    # --------------------------------------------------------

    if context.args:

        arg = context.args[0]

        if arg.startswith("verify"):

            if user_id:

                parts = arg.split("_")

                try:
                    target_chat_id = (
                        int(parts[1])
                        if len(parts) >= 2
                        else None
                    )
                except ValueError:
                    target_chat_id = None

                if (
                    target_chat_id
                    and user_id in user_verified_chats
                    and target_chat_id
                    in user_verified_chats[user_id]
                ):

                    if update.message:
                        await update.message.reply_text(
                            "You are already verified."
                        )

                else:

                    code = str(
                        random.randint(1000, 9999)
                    )

                    pending_verifications[user_id] = {
                        "code": code,
                        "args": arg
                    }

                    if update.message:

                        await update.message.reply_text(
                            "🔐 Verification Challenge\n\n"
                            "Please reply with the following "
                            f"number to prove you are human:\n\n"
                            f"**{code}**",
                            parse_mode="Markdown"
                        )

            return

    # --------------------------------------------------------
    # MAIN MENU
    # --------------------------------------------------------

    welcome_text = (
        "🤖 Welcome to Bmax Ultimate Command Center!\n\n"
        "Heya! I'm Bmax — your high-performance "
        "security, moderation, and community management bot.\n\n"
        "⚡ Elite Core Capabilities:\n"
        "• Advanced Anti-Spam & Shield\n"
        "• Smart Unwanted-Word Filter\n"
        "• NSFW Photo & GIF Detection\n"
        "• Interactive Human Verification\n\n"
        "📋 Select an option below:"
    )

    keyboard = [

        [
            InlineKeyboardButton(
                "➕ Add Me to Your Group",
                url=f"https://t.me/{bot_username}?startgroup=true"
            )
        ],

        [
            InlineKeyboardButton(
                "📢 Add Me to Your Channel",
                url=f"https://t.me/{bot_username}?startchannel=true"
            )
        ],

        [
            InlineKeyboardButton(
                "🛠 Admin Control Panel",
                callback_data="admin_panel"
            ),
            InlineKeyboardButton(
                "📜 Community Rules",
                callback_data="rules"
            )
        ],

        [
            InlineKeyboardButton(
                "❓ Help & Commands",
                callback_data="help"
            ),
            InlineKeyboardButton(
                "ℹ️ About Bmax",
                callback_data="about"
            )
        ],

        [
            InlineKeyboardButton(
                "🛡 Security Status",
                callback_data="status"
            ),
            InlineKeyboardButton(
                "⚡ Feature Showcase",
                callback_data="features"
            )
        ],

        [
            InlineKeyboardButton(
                "🌐 Official Support Community",
                url="https://t.me/Anime7p7"
            )
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    try:

        if update.message:

            await update.message.reply_text(
                welcome_text,
                reply_markup=reply_markup
            )

        elif update.callback_query:

            await update.callback_query.message.edit_text(
                welcome_text,
                reply_markup=reply_markup
            )

    except Exception as e:

        logger.error(
            f"Error displaying start menu: {e}"
        )


# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    help_text = (
        "❓ Bmax Command Reference Guide\n\n"
        "/start — Main dashboard\n"
        "/help — Help menu\n"
        "/rules — Community rules\n\n"
        "🛡️ Moderation automatically checks:\n"
        "• Unwanted/profanity words\n"
        "• NSFW photos\n"
        "• NSFW GIFs\n"
        "• Human verification"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu"
        )
    ]]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:

        await update.message.reply_text(
            help_text,
            reply_markup=reply_markup
        )

    elif update.callback_query:

        await update.callback_query.message.edit_text(
            help_text,
            reply_markup=reply_markup
        )


# ============================================================
# RULES
# ============================================================

async def rules_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    rules_text = (
        "📜 Community Guidelines\n\n"
        "1. 🚫 No spam or advertisements\n"
        "2. 🚫 No excessive profanity\n"
        "3. 🚫 No NSFW content\n"
        "4. 🤝 Respect other members\n"
        "5. 🛡️ Follow the verification system"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu"
        )
    ]]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:

        await update.message.reply_text(
            rules_text,
            reply_markup=reply_markup
        )

    elif update.callback_query:

        await update.callback_query.message.edit_text(
            rules_text,
            reply_markup=reply_markup
        )


# ============================================================
# ADMIN PANEL
# ============================================================

async def admin_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    admin_text = (
        "🛠 Admin Control Panel\n\n"
        "Make sure Bmax is an administrator in your group "
        "with permission to delete messages.\n\n"
        "Required permission:\n"
        "• 🗑 Delete messages"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu"
        )
    ]]

    await update.callback_query.message.edit_text(
        admin_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# ABOUT
# ============================================================

async def about_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    about_text = (
        "ℹ️ About Bmax Bot\n\n"
        "Next-generation Telegram moderation utility "
        "for community security and management."
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu"
        )
    ]]

    await update.callback_query.message.edit_text(
        about_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    status_text = (
        "🛡 Bmax Security Status\n\n"
        "• Core Engine: Online\n"
        "• Word Filter: Active\n"
        "• Photo Scanner: Active\n"
        "• GIF Scanner: Active\n"
        "• Verification: Active"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu"
        )
    ]]

    await update.callback_query.message.edit_text(
        status_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# FEATURES
# ============================================================

async def features_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    features_text = (
        "⚡ Feature Showcase\n\n"
        "🧹 Unwanted Word Protection\n"
        "🖼️ NSFW Photo Detection\n"
        "🎞️ NSFW GIF Detection\n"
        "🛡️ Human Verification\n"
        "🚫 Spam Protection\n"
        "🔗 Smart Moderation"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu"
        )
    ]]

    await update.callback_query.message.edit_text(
        features_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# SECURITY GUARD
# ============================================================

async def security_guard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    if not update.message:
        return

    message = update.message

    user_id = (
        message.from_user.id
        if message.from_user
        else None
    )

    # --------------------------------------------------------
    # BOT JOINED / NEW MEMBERS
    # --------------------------------------------------------

    if message.new_chat_members:

        for member in message.new_chat_members:

            if member.id == context.bot.id:
                continue

            welcome_text = (
                f"Welcome, {member.first_name}! 👋"
            )

            sent_msg = await message.reply_text(
                welcome_text
            )

            verify_payload = (
                f"verify_{message.chat_id}_{sent_msg.message_id}"
            )

            keyboard = [[
                InlineKeyboardButton(
                    "🛡 Verify you're human",
                    url=(
                        f"https://t.me/"
                        f"{context.bot.username}"
                        f"?start={verify_payload}"
                    )
                )
            ]]

            await sent_msg.edit_text(
                welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return

    # --------------------------------------------------------
    # IGNORE BOT'S OWN MESSAGES
    # --------------------------------------------------------

    if user_id and user_id == context.bot.id:
        return

    # --------------------------------------------------------
    # PRIVATE VERIFICATION
    # --------------------------------------------------------

    if (
        message.chat.type == "private"
        and user_id
        and user_id in pending_verifications
    ):

        user_text = (
            message.text or ""
        ).strip()

        expected_code = (
            pending_verifications[user_id]["code"]
        )

        arg = (
            pending_verifications[user_id]["args"]
        )

        parts = arg.split("_")

        try:
            target_chat_id = (
                int(parts[1])
                if len(parts) >= 2
                else None
            )
        except ValueError:
            target_chat_id = None

        if (
            target_chat_id
            and user_id in user_verified_chats
            and target_chat_id
            in user_verified_chats[user_id]
        ):

            await message.reply_text(
                "You are already verified."
            )

            return

        if user_text == expected_code:

            if user_id not in user_verified_chats:

                user_verified_chats[user_id] = set()

            if target_chat_id:

                user_verified_chats[user_id].add(
                    target_chat_id
                )

            del pending_verifications[user_id]

            await message.reply_text(
                "✅ You're all set!\n\n"
                "You're now verified and ready "
                "to chat in the group."
            )

            if len(parts) == 3:

                try:

                    target_msg_id = int(parts[2])

                    await context.bot.delete_message(
                        chat_id=target_chat_id,
                        message_id=target_msg_id
                    )

                except Exception as e:

                    logger.error(
                        f"Could not delete verification message: {e}"
                    )

            return

        else:

            await message.reply_text(
                "❌ Incorrect code.\n\n"
                f"Please send: {expected_code}"
            )

            return

    # --------------------------------------------------------
    # TEXT / CAPTION FILTER
    # --------------------------------------------------------

    text_content = (
        message.text
        or message.caption
        or ""
    )

    blocked_word = contains_blocked_word(
        text_content
    )

    if blocked_word:

        try:

            await message.delete()

            logger.info(
                f"Deleted message from "
                f"{user_id} containing blocked word: "
                f"{blocked_word}"
            )

        except Exception as e:

            logger.error(
                f"Failed to delete blocked-word message: {e}"
            )

        return

    # --------------------------------------------------------
    # PHOTO FILTER
    # --------------------------------------------------------

    if message.photo:

        is_nsfw, score = await check_photo(
            message
        )

        if is_nsfw:

            try:

                await message.delete()

                logger.info(
                    f"Deleted NSFW photo. "
                    f"Score: {score:.3f}"
                )

            except Exception as e:

                logger.error(
                    f"Failed to delete NSFW photo: {e}"
                )

            return

    # --------------------------------------------------------
    # GIF / ANIMATION FILTER
    # --------------------------------------------------------

    if message.animation:

        is_nsfw, score = await check_animation(
            message
        )

        if is_nsfw:

            try:

                await message.delete()

                logger.info(
                    f"Deleted NSFW GIF. "
                    f"Score: {score:.3f}"
                )

            except Exception as e:

                logger.error(
                    f"Failed to delete NSFW GIF: {e}"
                )

            return


# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    query = update.callback_query

    await query.answer()

    if query.data == "rules":

        await rules_command(
            update,
            context
        )

    elif query.data == "help":

        await help_command(
            update,
            context
        )

    elif query.data == "admin_panel":

        await admin_panel(
            update,
            context
        )

    elif query.data == "about":

        await about_command(
            update,
            context
        )

    elif query.data == "status":

        await status_command(
            update,
            context
        )

    elif query.data == "features":

        await features_command(
            update,
            context
        )

    elif query.data == "start_menu":

        await start(
            update,
            context
        )


# ============================================================
# MAIN
# ============================================================

def main():

    keep_alive()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        CommandHandler(
            "rules",
            rules_command
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            security_guard
        )
    )

    application.add_error_handler(
        error_handler
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
