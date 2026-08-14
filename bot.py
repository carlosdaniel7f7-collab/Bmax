import os
import re
import io
import logging
import threading
import asyncio
import random
import tempfile

from flask import Flask
from PIL import Image, UnidentifiedImageError

from nudenet import NudeDetector

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

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is missing."
    )


# ============================================================
# NUDENET NSFW DETECTOR
# ============================================================

try:

    nude_detector = NudeDetector()

    logger.info(
        "NudeNet NSFW detector initialized."
    )

except Exception as e:

    raise RuntimeError(
        f"Could not initialize NudeNet: {e}"
    )


# ============================================================
# NSFW DETECTION SETTINGS
# ============================================================

NSFW_LABELS = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
}

# Higher value = fewer false positives.
NSFW_SCORE_THRESHOLD = 0.65


def nudenet_scan(image_bytes: bytes):

    temp_path = None

    try:

        # NudeNet scans image files, so create a temporary image.
        with tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False
        ) as temp_file:

            temp_file.write(image_bytes)
            temp_path = temp_file.name

        detections = nude_detector.detect(
            temp_path
        )

        if not detections:
            return None

        for detection in detections:

            label = detection.get(
                "class",
                ""
            )

            score = float(
                detection.get(
                    "score",
                    0
                )
            )

            if (
                label in NSFW_LABELS
                and score >= NSFW_SCORE_THRESHOLD
            ):

                logger.info(
                    "NSFW detected: %s (%.2f)",
                    label,
                    score
                )

                return {
                    "label": label,
                    "score": score
                }

        return None

    except Exception as e:

        logger.error(
            "NudeNet scan failed: %s",
            e
        )

        return None

    finally:

        if temp_path:

            try:
                os.remove(temp_path)

            except Exception:
                pass


async def scan_image(image_bytes: bytes):

    return await asyncio.to_thread(
        nudenet_scan,
        image_bytes
    )


def is_explicit(result):

    return result is not None


# ============================================================
# RENDER KEEP-ALIVE WEB SERVER
# ============================================================

app = Flask("")


@app.route("/")
def home():
    return "Bmax Bot is alive and running!"


def run_flask():

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )


def keep_alive():

    thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    thread.start()


# ============================================================
# VERIFICATION STORAGE
# ============================================================

user_verified_chats = {}
pending_verifications = {}


# ============================================================
# BAD / UNWANTED WORD FILTER
# ============================================================

BLOCKED_WORDS = {

    # --------------------------------------------------------
    # PROFANITY
    # --------------------------------------------------------

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

    "bastard",
    "motherfucker",
    "motherfuckers",

    "dickhead",

    # --------------------------------------------------------
    # SEXUAL / NSFW TERMS
    # --------------------------------------------------------

    "porn",
    "porno",
    "pornography",

    "sex",
    "sexual",
    "sexy",

    "nude",
    "nudes",
    "nudity",
    "naked",

    "nsfw",
    "xxx",
    "hentai",

    "blowjob",
    "handjob",

    "masturbation",
    "masturbate",
    "masturbating",

    "orgasm",
    "cum",
    "cumming",

    "dildo",

    "pussy",
    "dick",
    "cock",

    "boobs",
    "tits",

    "erotic",
    "explicit",
    "lewd",
    "sexcam",
    "sexchat",
}


# ============================================================
# DISGUISED / LEETSPEAK WORDS
# ============================================================

DISGUISED_WORDS = {

    # Profanity
    "f1uck": "fuck",
    "f4ck": "fuck",
    "sh1t": "shit",
    "b1tch": "bitch",
    "a55hole": "asshole",

    # NSFW
    "p0rn": "porn",
    "p0rno": "porno",
    "p0rn0": "porno",

    "s3x": "sex",
    "s3xy": "sexy",

    "n4ked": "naked",
    "n00d": "nude",
    "n00des": "nudes",

    "n5fw": "nsfw",

    "h3ntai": "hentai",

    "c0ck": "cock",
    "d1ck": "dick",

    "b00bs": "boobs",
    "t1ts": "tits",

    "cvm": "cum",
}


# ============================================================
# NORMALIZE TEXT
# ============================================================

def normalize_text(text: str) -> str:

    if not text:
        return ""

    text = text.lower()

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

        text = text.replace(
            old,
            new
        )

    compact = re.sub(
        r"[\W_]+",
        "",
        text,
        flags=re.UNICODE
    )

    return compact


# ============================================================
# BAD WORD DETECTOR
# ============================================================

def contains_blocked_word(text: str):

    if not text:
        return None

    lowered = text.lower()

    # --------------------------------------------------------
    # NORMAL WORD MATCH
    # --------------------------------------------------------

    for word in BLOCKED_WORDS:

        pattern = (
            rf"(?<!\w)"
            rf"{re.escape(word)}"
            rf"(?!\w)"
        )

        if re.search(
            pattern,
            lowered
        ):

            return word

    # --------------------------------------------------------
    # DISGUISED WORD MATCH
    # --------------------------------------------------------

    for disguised, original in DISGUISED_WORDS.items():

        if disguised in lowered:

            return original

    # --------------------------------------------------------
    # PUNCTUATION / SPACE BYPASS
    # --------------------------------------------------------

    normalized = normalize_text(
        text
    )

    for word in BLOCKED_WORDS:

        if word in normalized:

            return word

    return None


# ============================================================
# PHOTO SCANNER
# ============================================================

async def check_photo(message):

    try:

        telegram_file = (
            await message.photo[-1].get_file()
        )

        image_bytes = (
            await telegram_file.download_as_bytearray()
        )

        result = await scan_image(
            bytes(image_bytes)
        )

        if result is None:

            return False, None

        explicit = is_explicit(
            result
        )

        return explicit, result

    except Exception as e:

        logger.error(
            "Photo scanning failed: %s",
            e
        )

        return False, None


# ============================================================
# GIF FRAME EXTRACTION
# ============================================================

def extract_gif_frames(
    gif_bytes: bytes,
    max_frames=5
):

    frames = []

    try:

        image = Image.open(
            io.BytesIO(gif_bytes)
        )

        frame_count = getattr(
            image,
            "n_frames",
            1
        )

        if frame_count <= 1:

            positions = [0]

        else:

            positions = [
                0,
                frame_count // 4,
                frame_count // 2,
                (frame_count * 3) // 4,
                frame_count - 1
            ]

        positions = list(
            dict.fromkeys(
                positions[:max_frames]
            )
        )

        for position in positions:

            try:

                image.seek(
                    position
                )

                frame = image.convert(
                    "RGB"
                )

                output = io.BytesIO()

                frame.save(
                    output,
                    format="JPEG",
                    quality=85
                )

                frames.append(
                    output.getvalue()
                )

            except Exception as e:

                logger.warning(
                    "Could not extract GIF frame %s: %s",
                    position,
                    e
                )

    except (
        UnidentifiedImageError,
        Exception
    ) as e:

        logger.error(
            "GIF processing failed: %s",
            e
        )

    return frames


# ============================================================
# ANIMATION SCANNER
# ============================================================

async def check_animation(message):

    try:

        # Scan Telegram thumbnail first.
        if message.animation.thumbnail:

            thumb_file = (
                await message.animation.thumbnail.get_file()
            )

            thumb_bytes = (
                await thumb_file.download_as_bytearray()
            )

            result = await scan_image(
                bytes(thumb_bytes)
            )

            if result and is_explicit(result):

                return True, result

        # Download animation.
        telegram_file = (
            await message.animation.get_file()
        )

        animation_bytes = (
            await telegram_file.download_as_bytearray()
        )

        frames = extract_gif_frames(
            bytes(animation_bytes),
            max_frames=5
        )

        highest_result = None
        highest_score = -1

        for frame in frames:

            result = await scan_image(
                frame
            )

            if not result:

                continue

            score = float(
                result.get(
                    "score",
                    0
                )
            )

            if score > highest_score:

                highest_score = score
                highest_result = result

            if is_explicit(result):

                return True, result

        return False, highest_result

    except Exception as e:

        logger.error(
            "Animation scanning failed: %s",
            e
        )

        return False, None


# ============================================================
# VIDEO THUMBNAIL SCANNER
# ============================================================

async def check_video(message):

    try:

        if not message.video.thumbnail:

            return False, None

        thumb_file = (
            await message.video.thumbnail.get_file()
        )

        thumb_bytes = (
            await thumb_file.download_as_bytearray()
        )

        result = await scan_image(
            bytes(thumb_bytes)
        )

        if result is None:

            return False, None

        return (
            is_explicit(result),
            result
        )

    except Exception as e:

        logger.error(
            "Video thumbnail scanning failed: %s",
            e
        )

        return False, None


# ============================================================
# DELETE HELPER
# ============================================================

async def delete_message_safely(
    message,
    reason=""
):

    try:

        await message.delete()

        logger.info(
            "Deleted message. Reason: %s",
            reason
        )

        return True

    except Exception as e:

        logger.error(
            "Could not delete message: %s",
            e
        )

        return False


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

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
):

    bot_username = (
        context.bot.username
    )

    user_id = (
        update.effective_user.id
        if update.effective_user
        else None
    )

    # --------------------------------------------------------
    # VERIFICATION
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
                        random.randint(
                            1000,
                            9999
                        )
                    )

                    pending_verifications[
                        user_id
                    ] = {
                        "code": code,
                        "args": arg
                    }

                    if update.message:

                        await update.message.reply_text(
                            "🔐 Verification Challenge\n\n"
                            "Please reply with the following "
                            "number to prove you are human:\n\n"
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
        "• Smart Bad-Word Filter\n"
        "• Smart NSFW Image Detection\n"
        "• Interactive Human Verification\n\n"
        "📋 Select an option below:"
    )

    keyboard = [

        [
            InlineKeyboardButton(
                "➕ Add Me to Your Group",
                url=(
                    f"https://t.me/"
                    f"{bot_username}"
                    f"?startgroup=true"
                )
            )
        ],

        [
            InlineKeyboardButton(
                "📢 Add Me to Your Channel",
                url=(
                    f"https://t.me/"
                    f"{bot_username}"
                    f"?startchannel=true"
                )
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

    reply_markup = InlineKeyboardMarkup(
        keyboard
    )

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
            "Error displaying start menu: %s",
            e
        )


# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    help_text = (
        "❓ Bmax Command Reference Guide\n\n"
        "/start — Main dashboard\n"
        "/help — Help menu\n"
        "/rules — Community rules\n\n"
        "🛡️ Moderation automatically checks:\n"
        "• Bad/profanity words\n"
        "• Sexual/NSFW words\n"
        "• NSFW photos\n"
        "• NSFW GIFs/animations\n"
        "• Video thumbnails\n"
        "• Human verification"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu"
        )
    ]]

    reply_markup = InlineKeyboardMarkup(
        keyboard
    )

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
):

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

    reply_markup = InlineKeyboardMarkup(
        keyboard
    )

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
):

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
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# ============================================================
# ABOUT
# ============================================================

async def about_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# ============================================================
# STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    status_text = (
        "🛡 Bmax Security Status\n\n"
        "• Core Engine: Online\n"
        "• Bad-Word Filter: Active\n"
        "• NSFW Text Filter: Active\n"
        "• NSFW Image Detection: Active\n"
        "• Photo Scanner: Active\n"
        "• GIF Scanner: Active\n"
        "• Video Thumbnail Scanner: Active\n"
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
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# ============================================================
# FEATURES
# ============================================================

async def features_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    features_text = (
        "⚡ Feature Showcase\n\n"
        "🧹 Bad Word Protection\n"
        "🔞 NSFW Text Protection\n"
        "🖼️ Smart NSFW Image Detection\n"
        "🎞️ GIF / Animation Detection\n"
        "🎥 Video Thumbnail Detection\n"
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
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# ============================================================
# SECURITY GUARD
# ============================================================

async def security_guard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    message = update.message

    user_id = (
        message.from_user.id
        if message.from_user
        else None
    )

    # --------------------------------------------------------
    # NEW MEMBERS
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
                f"verify_"
                f"{message.chat_id}_"
                f"{sent_msg.message_id}"
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
                reply_markup=InlineKeyboardMarkup(
                    keyboard
                )
            )

        return

    # --------------------------------------------------------
    # IGNORE BOT'S OWN MESSAGES
    # --------------------------------------------------------

    if (
        user_id
        and user_id == context.bot.id
    ):

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
            pending_verifications[
                user_id
            ]["code"]
        )

        arg = (
            pending_verifications[
                user_id
            ]["args"]
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

                user_verified_chats[
                    user_id
                ] = set()

            if target_chat_id:

                user_verified_chats[
                    user_id
                ].add(
                    target_chat_id
                )

            del pending_verifications[
                user_id
            ]

            await message.reply_text(
                "✅ You're all set!\n\n"
                "You're now verified and ready "
                "to chat in the group."
            )

            if len(parts) == 3:

                try:

                    target_msg_id = int(
                        parts[2]
                    )

                    await context.bot.delete_message(
                        chat_id=target_chat_id,
                        message_id=target_msg_id
                    )

                except Exception as e:

                    logger.error(
                        "Could not delete verification "
                        "message: %s",
                        e
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

        await delete_message_safely(
            message,
            f"blocked word: {blocked_word}"
        )

        return

    # --------------------------------------------------------
    # PHOTO FILTER
    # --------------------------------------------------------

    if message.photo:

        is_nsfw, result = (
            await check_photo(
                message
            )
        )

        if is_nsfw:

            await delete_message_safely(
                message,
                "NSFW photo detected"
            )

            return

    # --------------------------------------------------------
    # GIF / ANIMATION FILTER
    # --------------------------------------------------------

    if message.animation:

        is_nsfw, result = (
            await check_animation(
                message
            )
        )

        if is_nsfw:

            await delete_message_safely(
                message,
                "NSFW animation detected"
            )

            return

    # --------------------------------------------------------
    # VIDEO FILTER
    # --------------------------------------------------------

    if message.video:

        is_nsfw, result = (
            await check_video(
                message
            )
        )

        if is_nsfw:

            await delete_message_safely(
                message,
                "NSFW video thumbnail detected"
            )

            return


# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":
    main()
