import os
import re
import logging
import threading
import asyncio
import random
import tempfile
import subprocess
import shutil

from flask import Flask

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
# ENVIRONMENT
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")


# ============================================================
# NUDENET
# ============================================================

try:
    nude_detector = NudeDetector()
    logger.info("NudeNet NSFW detector initialized.")
except Exception as e:
    raise RuntimeError(f"Could not initialize NudeNet: {e}")


# ============================================================
# NSFW SETTINGS
# ============================================================

NSFW_LABELS = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "MALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
}

NSFW_SCORE_THRESHOLD = 0.50


# ============================================================
# FAST MEDIA SCANNING SETTINGS
# ============================================================

# IMPORTANT:
# Lower number = much faster scanning.
#
# 16 frames gives good coverage while being much faster
# than scanning 40 frames.

MEDIA_FRAME_COUNT = 16

# Maximum number of frames for extremely short media.
MIN_MEDIA_FRAMES = 8

# Maximum extraction FPS.
MAX_FPS = 5

# JPEG quality.
FRAME_QUALITY = "5"


# ============================================================
# NUDENET IMAGE SCANNER
# ============================================================

def nudenet_scan(image_bytes: bytes):

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False
        ) as temp_file:

            temp_file.write(image_bytes)
            temp_path = temp_file.name

        detections = nude_detector.detect(temp_path)

        if not detections:
            return None

        best_detection = None

        for detection in detections:

            label = detection.get("class", "")
            score = float(detection.get("score", 0))

            if (
                label in NSFW_LABELS
                and score >= NSFW_SCORE_THRESHOLD
            ):

                if (
                    best_detection is None
                    or score > best_detection["score"]
                ):

                    best_detection = {
                        "label": label,
                        "score": score
                    }

        if best_detection:

            logger.warning(
                "NSFW detected: %s %.3f",
                best_detection["label"],
                best_detection["score"]
            )

            return best_detection

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


# ============================================================
# SCAN FRAME
# ============================================================

async def scan_frame_file(frame_path):

    try:

        with open(frame_path, "rb") as file:
            image_bytes = file.read()

        return await scan_image(image_bytes)

    except Exception as e:

        logger.error(
            "Frame scan failed: %s",
            e
        )

        return None


# ============================================================
# FFMPEG CHECK
# ============================================================

def ffmpeg_available():

    return (
        shutil.which("ffmpeg") is not None
        and shutil.which("ffprobe") is not None
    )


# ============================================================
# GET MEDIA DURATION
# ============================================================

async def get_media_duration(media_path):

    try:

        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            media_path
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            return None

        value = stdout.decode(
            errors="ignore"
        ).strip()

        duration = float(value)

        if duration <= 0:
            return None

        return duration

    except Exception as e:

        logger.warning(
            "Could not determine media duration: %s",
            e
        )

        return None


# ============================================================
# CALCULATE FAST FRAME COUNT
# ============================================================

def calculate_frame_count(duration):

    if not duration:
        return MEDIA_FRAME_COUNT

    # Very short GIF/video
    if duration <= 2:
        return MIN_MEDIA_FRAMES

    # Normal media
    return MEDIA_FRAME_COUNT


# ============================================================
# EXTRACT + SCAN MEDIA
# ============================================================

async def extract_and_scan_media(
    media_bytes: bytes,
    extension=".mp4"
):

    work_dir = tempfile.mkdtemp(
        prefix="bmax_media_"
    )

    media_path = os.path.join(
        work_dir,
        f"media{extension}"
    )

    frames_pattern = os.path.join(
        work_dir,
        "frame_%03d.jpg"
    )

    try:

        # ----------------------------------------------------
        # SAVE MEDIA
        # ----------------------------------------------------

        with open(
            media_path,
            "wb"
        ) as file:

            file.write(media_bytes)

        # ----------------------------------------------------
        # FFMPEG CHECK
        # ----------------------------------------------------

        if not ffmpeg_available():

            logger.error(
                "FFmpeg/FFprobe is not installed."
            )

            return False, None

        # ----------------------------------------------------
        # GET DURATION
        # ----------------------------------------------------

        duration = await get_media_duration(
            media_path
        )

        if duration:

            logger.info(
                "Media duration: %.2f seconds",
                duration
            )

        # ----------------------------------------------------
        # FRAME COUNT
        # ----------------------------------------------------

        frame_count = calculate_frame_count(
            duration
        )

        logger.info(
            "Fast scan: approximately %d frames.",
            frame_count
        )

        # ----------------------------------------------------
        # EXTRACT FRAMES
        # ----------------------------------------------------

        if duration:

            fps = frame_count / duration

            fps = min(
                fps,
                MAX_FPS
            )

            filter_value = (
                f"fps={fps:.4f}"
            )

        else:

            filter_value = (
                f"fps={MAX_FPS}"
            )

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            media_path,
            "-vf",
            filter_value,
            "-frames:v",
            str(frame_count),
            "-q:v",
            FRAME_QUALITY,
            frames_pattern
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:

            logger.error(
                "FFmpeg extraction failed: %s",
                stderr.decode(
                    errors="ignore"
                )[-2000:]
            )

            return False, None

        # ----------------------------------------------------
        # GET FRAME FILES
        # ----------------------------------------------------

        frame_files = sorted(
            [
                os.path.join(
                    work_dir,
                    filename
                )
                for filename in os.listdir(
                    work_dir
                )
                if filename.startswith("frame_")
                and filename.endswith(".jpg")
            ]
        )

        if not frame_files:

            logger.warning(
                "No frames extracted."
            )

            return False, None

        logger.info(
            "Actually extracted %d frames.",
            len(frame_files)
        )

        # ----------------------------------------------------
        # SCAN FRAMES
        # ----------------------------------------------------

        for index, frame_path in enumerate(
            frame_files,
            start=1
        ):

            result = await scan_frame_file(
                frame_path
            )

            # STOP IMMEDIATELY WHEN NSFW IS FOUND
            if result:

                logger.warning(
                    "NSFW detected in frame %d/%d",
                    index,
                    len(frame_files)
                )

                return True, result

        logger.info(
            "All %d frames passed.",
            len(frame_files)
        )

        return False, None

    except Exception as e:

        logger.error(
            "Media scanning failed: %s",
            e
        )

        return False, None

    finally:

        shutil.rmtree(
            work_dir,
            ignore_errors=True
        )


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

        if result:
            return True, result

        return False, None

    except Exception as e:

        logger.error(
            "Photo scan failed: %s",
            e
        )

        return False, None


# ============================================================
# TELEGRAM ANIMATION / GIF
# ============================================================

async def check_animation(message):

    try:

        logger.info(
            "Downloading animation..."
        )

        telegram_file = (
            await message.animation.get_file()
        )

        media_bytes = (
            await telegram_file.download_as_bytearray()
        )

        logger.info(
            "Animation downloaded. Starting fast NSFW scan."
        )

        return await extract_and_scan_media(
            bytes(media_bytes),
            extension=".mp4"
        )

    except Exception as e:

        logger.error(
            "Animation scan failed: %s",
            e
        )

        return False, None


# ============================================================
# VIDEO
# ============================================================

async def check_video(message):

    try:

        logger.info(
            "Downloading video..."
        )

        telegram_file = (
            await message.video.get_file()
        )

        media_bytes = (
            await telegram_file.download_as_bytearray()
        )

        return await extract_and_scan_media(
            bytes(media_bytes),
            extension=".mp4"
        )

    except Exception as e:

        logger.error(
            "Video scan failed: %s",
            e
        )

        return False, None


# ============================================================
# GIF DOCUMENT
# ============================================================

async def check_gif_document(message):

    try:

        if not message.document:
            return False, None

        mime_type = (
            message.document.mime_type
            or ""
        ).lower()

        file_name = (
            message.document.file_name
            or ""
        ).lower()

        is_gif = (
            mime_type == "image/gif"
            or file_name.endswith(".gif")
        )

        if not is_gif:
            return False, None

        logger.info(
            "GIF document detected."
        )

        telegram_file = (
            await message.document.get_file()
        )

        media_bytes = (
            await telegram_file.download_as_bytearray()
        )

        return await extract_and_scan_media(
            bytes(media_bytes),
            extension=".gif"
        )

    except Exception as e:

        logger.error(
            "GIF document scan failed: %s",
            e
        )

        return False, None


# ============================================================
# DELETE MESSAGE
# ============================================================

async def delete_message_safely(
    message,
    reason=""
):

    try:

        await message.delete()

        logger.warning(
            "MESSAGE DELETED: %s",
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
# BLOCKED WORDS
# ============================================================

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

    "bastard",

    "motherfucker",
    "motherfuckers",

    "dickhead",

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

    "onlyfans",

    "anal",
    "vagina",
    "penis",
    "genitals",
}


# ============================================================
# DISGUISED WORDS
# ============================================================

DISGUISED_WORDS = {

    "f1uck": "fuck",
    "f4ck": "fuck",

    "sh1t": "shit",

    "b1tch": "bitch",

    "a55hole": "asshole",

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

    "v4gina": "vagina",
    "p3nis": "penis",
}


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text: str):

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

    return re.sub(
        r"[\W_]+",
        "",
        text,
        flags=re.UNICODE
    )


# ============================================================
# BLOCKED WORD DETECTOR
# ============================================================

def contains_blocked_word(text: str):

    if not text:
        return None

    lowered = text.lower()

    # Normal words
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

    # Explicit leetspeak
    for disguised, original in DISGUISED_WORDS.items():

        if disguised in lowered:
            return original

    # Spaces/punctuation between letters
    normalized = normalize_text(text)

    for word in BLOCKED_WORDS:

        if word in normalized:
            return word

    return None


# ============================================================
# FLASK KEEP ALIVE
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
# VERIFICATION
# ============================================================

user_verified_chats = {}
pending_verifications = {}


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    bot_username = context.bot.username

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

                    target_chat_id = int(
                        parts[1]
                    )

                except (
                    ValueError,
                    IndexError
                ):

                    target_chat_id = None

                if (
                    target_chat_id
                    and user_id in user_verified_chats
                    and target_chat_id in user_verified_chats[user_id]
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

                    pending_verifications[user_id] = {
                        "code": code,
                        "args": arg
                    }

                    if update.message:

                        await update.message.reply_text(
                            "🔐 Verification Challenge\n\n"
                            "Reply with the following number "
                            "to prove you are human:\n\n"
                            f"**{code}**",
                            parse_mode="Markdown"
                        )

            return

    # --------------------------------------------------------
    # MAIN MENU
    # --------------------------------------------------------

    welcome_text = (
        "🤖 Welcome to Bmax Ultimate Command Center!\n\n"
        "Heya! I'm Bmax — your moderation and "
        "community security bot.\n\n"
        "⚡ Features:\n"
        "• Anti-Spam & moderation\n"
        "• Bad-word filtering\n"
        "• NSFW photo detection\n"
        "• Fast multi-frame GIF detection\n"
        "• Fast multi-frame video detection\n"
        "• GIF document detection\n"
        "• Human verification\n\n"
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
            "Could not display start menu: %s",
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
        "❓ Bmax Command Reference\n\n"
        "/start — Main dashboard\n"
        "/help — Help menu\n"
        "/rules — Community rules\n\n"
        "🛡️ Automatic moderation:\n"
        "• Bad/profanity words\n"
        "• Sexual/NSFW words\n"
        "• NSFW photos\n"
        "• Fast multi-frame GIF scanning\n"
        "• GIF document scanning\n"
        "• Fast multi-frame video scanning\n"
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
        "5. 🛡️ Follow verification requirements"
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
        "Bmax must be an administrator in the group.\n\n"
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
        "Telegram community moderation utility "
        "with automated text and media protection."
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
        "• Fast GIF Scanning: Active\n"
        "• GIF Document Scanning: Active\n"
        "• Fast Video Scanning: Active\n"
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
        "🖼️ NSFW Image Detection\n"
        "🎞️ Fast GIF Detection\n"
        "📁 GIF Document Detection\n"
        "🎥 Fast Video Detection\n"
        "🛡️ Human Verification\n"
        "🚫 Spam Protection"
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

    # ========================================================
    # NEW MEMBERS
    # ========================================================

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

    # ========================================================
    # IGNORE BOT
    # ========================================================

    if (
        user_id
        and user_id == context.bot.id
    ):
        return

    # ========================================================
    # PRIVATE VERIFICATION
    # ========================================================

    if (
        message.chat.type == "private"
        and user_id
        and user_id in pending_verifications
    ):

        user_text = (
            message.text or ""
        ).strip()

        verification = (
            pending_verifications[user_id]
        )

        expected_code = verification["code"]
        arg = verification["args"]

        parts = arg.split("_")

        try:

            target_chat_id = int(
                parts[1]
            )

        except (
            ValueError,
            IndexError
        ):

            target_chat_id = None

        if (
            target_chat_id
            and user_id in user_verified_chats
            and target_chat_id in user_verified_chats[user_id]
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

                    target_msg_id = int(
                        parts[2]
                    )

                    await context.bot.delete_message(
                        chat_id=target_chat_id,
                        message_id=target_msg_id
                    )

                except Exception as e:

                    logger.error(
                        "Could not delete verification message: %s",
                        e
                    )

            return

        await message.reply_text(
            "❌ Incorrect code.\n\n"
            f"Please send: {expected_code}"
        )

        return

    # ========================================================
    # TEXT / CAPTION
    # ========================================================

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

    # ========================================================
    # PHOTO
    # ========================================================

    if message.photo:

        is_nsfw, result = await check_photo(
            message
        )

        if is_nsfw:

            await delete_message_safely(
                message,
                f"NSFW photo: {result}"
            )

            return

    # ========================================================
    # TELEGRAM ANIMATION / GIF
    # ========================================================

    if message.animation:

        is_nsfw, result = await check_animation(
            message
        )

        if is_nsfw:

            await delete_message_safely(
                message,
                f"NSFW GIF/animation: {result}"
            )

            return

    # ========================================================
    # VIDEO
    # ========================================================

    if message.video:

        is_nsfw, result = await check_video(
            message
        )

        if is_nsfw:

            await delete_message_safely(
                message,
                f"NSFW video: {result}"
            )

            return

    # ========================================================
    # GIF DOCUMENT
    # ========================================================

    if message.document:

        mime_type = (
            message.document.mime_type
            or ""
        ).lower()

        file_name = (
            message.document.file_name
            or ""
        ).lower()

        if (
            mime_type == "image/gif"
            or file_name.endswith(".gif")
        ):

            is_nsfw, result = await check_gif_document(
                message
            )

            if is_nsfw:

                await delete_message_safely(
                    message,
                    f"NSFW GIF document: {result}"
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
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Exception while handling an update:",
        exc_info=context.error
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

    logger.info(
        "Starting Bmax bot..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
