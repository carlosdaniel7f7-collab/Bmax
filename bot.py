import os
import re
import logging
import threading
import asyncio
import random
import tempfile
import shutil
import time

from flask import Flask

from nudenet import NudeDetector

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("bmax")


# ============================================================
# ENVIRONMENT
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is missing."
    )


# ============================================================
# GLOBAL SETTINGS
# ============================================================

# NudeNet is initialized lazily.
# This prevents the application from crashing before Telegram
# and Flask are fully started if the model has a problem.
nude_detector = None
nude_detector_lock = asyncio.Lock()


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
# MEDIA SETTINGS
# ============================================================

# Number of frames checked from videos/GIFs.
MEDIA_FRAME_COUNT = 6

# Maximum extraction FPS.
MAX_FPS = 1

# Resize extracted frames.
FRAME_WIDTH = 480

# JPEG quality.
FRAME_QUALITY = "5"

# Keep this LOW on Render.
#
# NudeNet is CPU-heavy. Running many ONNX inferences at once
# can cause memory/CPU problems on small instances.
SCAN_CONCURRENCY = 2

# Maximum downloaded media size.
# 50 MB is a reasonable safety limit for this type of bot.
MAX_MEDIA_BYTES = 50 * 1024 * 1024


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
# VERIFICATION STORAGE
# ============================================================

# {
#     user_id: {
#         chat_id,
#         message_id,
#         code,
#         created_at
#     }
# }
pending_verifications = {}

# {
#     user_id: {
#         chat_id,
#         ...
#     }
# }
verified_users = {}


# ============================================================
# SIMPLE SPAM/RATE LIMIT STORAGE
# ============================================================

user_message_times = {}

SPAM_WINDOW = 8
SPAM_LIMIT = 8


# ============================================================
# NUDE NET INITIALIZATION
# ============================================================

def initialize_nudenet():
    """
    Initialize NudeNet safely.

    This runs in a background thread so the Telegram bot can
    start even if model initialization takes some time.
    """

    global nude_detector

    try:
        logger.info("Initializing NudeNet...")

        detector = NudeDetector()

        nude_detector = detector

        logger.info(
            "NudeNet NSFW detector initialized successfully."
        )

        return True

    except Exception:
        logger.exception(
            "NudeNet initialization failed."
        )

        nude_detector = None

        return False


async def ensure_nudenet():
    """
    Make sure NudeNet is initialized before scanning.
    """

    global nude_detector

    if nude_detector is not None:
        return True

    async with nude_detector_lock:

        if nude_detector is not None:
            return True

        result = await asyncio.to_thread(
            initialize_nudenet
        )

        return result


# ============================================================
# NUDE NET IMAGE SCANNER
# ============================================================

def nudenet_scan(image_bytes: bytes):

    global nude_detector

    if nude_detector is None:
        return None

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False,
        ) as temp_file:

            temp_file.write(image_bytes)
            temp_path = temp_file.name

        detections = nude_detector.detect(
            temp_path
        )

        if not detections:
            return None

        best_detection = None

        for detection in detections:

            label = detection.get(
                "class",
                "",
            )

            try:
                score = float(
                    detection.get(
                        "score",
                        0,
                    )
                )
            except Exception:
                score = 0.0

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
                        "score": score,
                    }

        if best_detection:

            logger.warning(
                "NSFW detected: %s %.3f",
                best_detection["label"],
                best_detection["score"],
            )

            return best_detection

        return None

    except Exception:
        logger.exception(
            "NudeNet scan failed."
        )

        return None

    finally:

        if temp_path:

            try:
                os.remove(temp_path)
            except Exception:
                pass


async def scan_image(image_bytes: bytes):

    if not image_bytes:
        return None

    ready = await ensure_nudenet()

    if not ready:
        logger.error(
            "NudeNet is unavailable. "
            "Skipping AI image scan."
        )

        return None

    return await asyncio.to_thread(
        nudenet_scan,
        image_bytes,
    )


# ============================================================
# FRAME SCANNER
# ============================================================

async def scan_frame_file(frame_path):

    try:

        with open(
            frame_path,
            "rb",
        ) as file:

            image_bytes = file.read()

        return await scan_image(
            image_bytes
        )

    except Exception:
        logger.exception(
            "Frame scan failed."
        )

        return None


# ============================================================
# FFMPEG CHECK
# ============================================================

def ffmpeg_available():

    ffmpeg = shutil.which(
        "ffmpeg"
    )

    ffprobe = shutil.which(
        "ffprobe"
    )

    return (
        ffmpeg is not None
        and ffprobe is not None
    )


# ============================================================
# MEDIA DURATION
# ============================================================

async def get_media_duration(
    media_path,
):

    try:

        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            media_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            return None

        value = stdout.decode(
            errors="ignore"
        ).strip()

        if not value:
            return None

        duration = float(value)

        if duration <= 0:
            return None

        return duration

    except Exception:
        logger.exception(
            "Could not determine media duration."
        )

        return None


# ============================================================
# FRAME COUNT
# ============================================================

def calculate_frame_count(
    duration,
):

    if not duration:
        return MEDIA_FRAME_COUNT

    if duration <= 2:
        return MEDIA_FRAME_COUNT

    return MEDIA_FRAME_COUNT


# ============================================================
# PARALLEL FRAME SCANNING
# ============================================================

async def scan_frames_parallel(
    frame_files,
):

    semaphore = asyncio.Semaphore(
        SCAN_CONCURRENCY
    )

    async def scan_one(
        index,
        frame_path,
    ):

        async with semaphore:

            logger.info(
                "Scanning frame %d/%d",
                index,
                len(frame_files),
            )

            result = await scan_frame_file(
                frame_path
            )

            return index, result

    tasks = [
        asyncio.create_task(
            scan_one(
                index,
                frame_path,
            )
        )
        for index, frame_path in enumerate(
            frame_files,
            start=1,
        )
    ]

    try:

        for completed_task in asyncio.as_completed(
            tasks
        ):

            index, result = await completed_task

            if result:

                logger.warning(
                    "NSFW detected in frame %d/%d",
                    index,
                    len(frame_files),
                )

                for task in tasks:

                    if not task.done():
                        task.cancel()

                await asyncio.gather(
                    *tasks,
                    return_exceptions=True,
                )

                return True, result

        return False, None

    except Exception:

        for task in tasks:

            if not task.done():
                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        raise


# ============================================================
# EXTRACT + SCAN MEDIA
# ============================================================

async def extract_and_scan_media(
    media_bytes: bytes,
    extension=".mp4",
):

    if not media_bytes:
        return False, None

    if len(media_bytes) > MAX_MEDIA_BYTES:

        logger.warning(
            "Media exceeds size limit."
        )

        return False, None

    work_dir = tempfile.mkdtemp(
        prefix="bmax_media_"
    )

    media_path = os.path.join(
        work_dir,
        f"media{extension}",
    )

    frames_pattern = os.path.join(
        work_dir,
        "frame_%03d.jpg",
    )

    try:

        # ----------------------------------------------------
        # SAVE MEDIA
        # ----------------------------------------------------

        with open(
            media_path,
            "wb",
        ) as file:

            file.write(media_bytes)

        # ----------------------------------------------------
        # CHECK FFMPEG
        # ----------------------------------------------------

        if not ffmpeg_available():

            logger.error(
                "FFmpeg or FFprobe is not installed."
            )

            return False, None

        # ----------------------------------------------------
        # DURATION
        # ----------------------------------------------------

        duration = await get_media_duration(
            media_path
        )

        if duration:

            logger.info(
                "Media duration: %.2f seconds",
                duration,
            )

        # ----------------------------------------------------
        # FRAME COUNT
        # ----------------------------------------------------

        frame_count = calculate_frame_count(
            duration
        )

        # ----------------------------------------------------
        # FRAME EXTRACTION
        # ----------------------------------------------------

        if duration:

            fps = frame_count / duration

            fps = min(
                fps,
                MAX_FPS,
            )

            filter_value = (
                f"fps={fps:.4f},"
                f"scale={FRAME_WIDTH}:-2"
            )

        else:

            filter_value = (
                f"fps={MAX_FPS},"
                f"scale={FRAME_WIDTH}:-2"
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
            frames_pattern,
        ]

        logger.info(
            "Extracting up to %d frames...",
            frame_count,
        )

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:

            logger.error(
                "FFmpeg extraction failed: %s",
                stderr.decode(
                    errors="ignore"
                )[-2000:],
            )

            return False, None

        # ----------------------------------------------------
        # FIND FRAMES
        # ----------------------------------------------------

        frame_files = sorted(
            [
                os.path.join(
                    work_dir,
                    filename,
                )
                for filename in os.listdir(
                    work_dir
                )
                if filename.startswith(
                    "frame_"
                )
                and filename.endswith(
                    ".jpg"
                )
            ]
        )

        if not frame_files:

            logger.warning(
                "No frames extracted."
            )

            return False, None

        logger.info(
            "Extracted %d frames.",
            len(frame_files),
        )

        # ----------------------------------------------------
        # SCAN
        # ----------------------------------------------------

        is_nsfw, result = await scan_frames_parallel(
            frame_files
        )

        return is_nsfw, result

    except Exception:
        logger.exception(
            "Media scanning failed."
        )

        return False, None

    finally:

        shutil.rmtree(
            work_dir,
            ignore_errors=True,
        )


# ============================================================
# TELEGRAM FILE SIZE
# ============================================================

def telegram_file_too_large(
    telegram_file,
):

    file_size = getattr(
        telegram_file,
        "file_size",
        None,
    )

    if not file_size:
        return False

    return file_size > MAX_MEDIA_BYTES


# ============================================================
# PHOTO SCANNER
# ============================================================

async def check_photo(
    message,
):

    try:

        telegram_file = await message.photo[-1].get_file()

        if telegram_file_too_large(
            telegram_file
        ):

            logger.warning(
                "Photo too large."
            )

            return False, None

        image_bytes = await telegram_file.download_as_bytearray()

        result = await scan_image(
            bytes(image_bytes)
        )

        if result:
            return True, result

        return False, None

    except Exception:
        logger.exception(
            "Photo scan failed."
        )

        return False, None


# ============================================================
# ANIMATION / GIF
# ============================================================

async def check_animation(
    message,
):

    try:

        logger.info(
            "Downloading animation..."
        )

        telegram_file = await message.animation.get_file()

        if telegram_file_too_large(
            telegram_file
        ):

            logger.warning(
                "Animation too large."
            )

            return False, None

        media_bytes = await telegram_file.download_as_bytearray()

        logger.info(
            "Animation downloaded."
        )

        return await extract_and_scan_media(
            bytes(media_bytes),
            extension=".mp4",
        )

    except Exception:
        logger.exception(
            "Animation scan failed."
        )

        return False, None


# ============================================================
# VIDEO
# ============================================================

async def check_video(
    message,
):

    try:

        logger.info(
            "Downloading video..."
        )

        telegram_file = await message.video.get_file()

        if telegram_file_too_large(
            telegram_file
        ):

            logger.warning(
                "Video too large."
            )

            return False, None

        media_bytes = await telegram_file.download_as_bytearray()

        logger.info(
            "Video downloaded."
        )

        return await extract_and_scan_media(
            bytes(media_bytes),
            extension=".mp4",
        )

    except Exception:
        logger.exception(
            "Video scan failed."
        )

        return False, None


# ============================================================
# GIF DOCUMENT
# ============================================================

async def check_gif_document(
    message,
):

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

        telegram_file = await message.document.get_file()

        if telegram_file_too_large(
            telegram_file
        ):

            logger.warning(
                "GIF document too large."
            )

            return False, None

        media_bytes = await telegram_file.download_as_bytearray()

        return await extract_and_scan_media(
            bytes(media_bytes),
            extension=".gif",
        )

    except Exception:
        logger.exception(
            "GIF document scan failed."
        )

        return False, None


# ============================================================
# DELETE MESSAGE
# ============================================================

async def delete_message_safely(
    message,
    reason="",
):

    try:

        await message.delete()

        logger.warning(
            "MESSAGE DELETED: %s",
            reason,
        )

        return True

    except Exception as e:

        logger.error(
            "Could not delete message: %s",
            e,
        )

        return False


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(
    text: str,
):

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
            new,
        )

    return re.sub(
        r"[\W_]+",
        "",
        text,
        flags=re.UNICODE,
    )


# ============================================================
# BLOCKED WORD DETECTOR
# ============================================================

def contains_blocked_word(
    text: str,
):

    if not text:
        return None

    lowered = text.lower()

    # --------------------------------------------------------
    # NORMAL WORDS
    # --------------------------------------------------------

    for word in BLOCKED_WORDS:

        pattern = (
            rf"(?<!\w)"
            rf"{re.escape(word)}"
            rf"(?!\w)"
        )

        if re.search(
            pattern,
            lowered,
        ):

            return word

    # --------------------------------------------------------
    # EXPLICIT LEETSPEAK
    # --------------------------------------------------------

    for disguised, original in DISGUISED_WORDS.items():

        if disguised in lowered:
            return original

    # --------------------------------------------------------
    # PUNCTUATION / SPACES
    # --------------------------------------------------------

    normalized = normalize_text(
        text
    )

    for word in BLOCKED_WORDS:

        if word in normalized:
            return word

    return None


# ============================================================
# FLASK KEEP ALIVE
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():

    return (
        "Bmax Bot is alive and running!"
    )


@app.route("/health")
def health():

    return {
        "status": "ok",
        "nudenet": nude_detector is not None,
    }


def run_flask():

    port = int(
        os.getenv(
            "PORT",
            "10000",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


def keep_alive():

    thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )

    thread.start()


# ============================================================
# MAIN MENU
# ============================================================

def main_keyboard(
    bot_username,
):

    keyboard = [

        [
            InlineKeyboardButton(
                "➕ Add Me to Your Group",
                url=(
                    f"https://t.me/"
                    f"{bot_username}"
                    f"?startgroup=true"
                ),
            ),
        ],

        [
            InlineKeyboardButton(
                "📢 Add Me to Your Channel",
                url=(
                    f"https://t.me/"
                    f"{bot_username}"
                    f"?startchannel=true"
                ),
            ),
        ],

        [
            InlineKeyboardButton(
                "🛠 Admin Control Panel",
                callback_data="admin_panel",
            ),

            InlineKeyboardButton(
                "📜 Community Rules",
                callback_data="rules",
            ),
        ],

        [
            InlineKeyboardButton(
                "❓ Help & Commands",
                callback_data="help",
            ),

            InlineKeyboardButton(
                "ℹ️ About Bmax",
                callback_data="about",
            ),
        ],

        [
            InlineKeyboardButton(
                "🛡 Security Status",
                callback_data="status",
            ),

            InlineKeyboardButton(
                "⚡ Feature Showcase",
                callback_data="features",
            ),
        ],

        [
            InlineKeyboardButton(
                "🌐 Official Support Community",
                url="https://t.me/Anime7p7",
            ),
        ],
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    user_id = (
        user.id
        if user
        else None
    )

    # --------------------------------------------------------
    # VERIFICATION LINK
    # --------------------------------------------------------

    if context.args:

        arg = context.args[0]

        if arg.startswith("verify_"):

            if not user_id:
                return

            parts = arg.split("_")

            try:

                target_chat_id = int(
                    parts[1]
                )

            except (
                ValueError,
                IndexError,
            ):

                target_chat_id = None

            if not target_chat_id:

                if update.message:

                    await update.message.reply_text(
                        "❌ Invalid verification link."
                    )

                return

            existing_chats = verified_users.get(
                user_id,
                set(),
            )

            if target_chat_id in existing_chats:

                if update.message:

                    await update.message.reply_text(
                        "✅ You are already verified."
                    )

                return

            code = str(
                random.randint(
                    1000,
                    9999,
                )
            )

            pending_verifications[
                user_id
            ] = {
                "code": code,
                "chat_id": target_chat_id,
                "message_id": (
                    int(parts[2])
                    if len(parts) >= 3
                    and parts[2].isdigit()
                    else None
                ),
                "created_at": time.time(),
            }

            if update.message:

                await update.message.reply_text(
                    "🔐 Verification Challenge\n\n"
                    "Reply with the following number "
                    "to prove you are human:\n\n"
                    f"**{code}**",
                    parse_mode="Markdown",
                )

            return

    # --------------------------------------------------------
    # NORMAL START MENU
    # --------------------------------------------------------

    bot_username = context.bot.username

    welcome_text = (
        "🤖 Welcome to Bmax Ultimate Command Center!\n\n"
        "Heya! I'm Bmax — your moderation and "
        "community security bot.\n\n"
        "⚡ Features:\n"
        "• Anti-Spam & moderation\n"
        "• Bad-word filtering\n"
        "• NSFW photo detection\n"
        "• Fast GIF detection\n"
        "• GIF document detection\n"
        "• Fast video detection\n"
        "• Human verification\n\n"
        "📋 Select an option below:"
    )

    keyboard = main_keyboard(
        bot_username
    )

    try:

        if update.message:

            await update.message.reply_text(
                welcome_text,
                reply_markup=keyboard,
            )

        elif update.callback_query:

            await update.callback_query.message.edit_text(
                welcome_text,
                reply_markup=keyboard,
            )

    except Exception:
        logger.exception(
            "Could not display main menu."
        )


# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "❓ Bmax Command Reference\n\n"
        "/start — Main dashboard\n"
        "/help — Help menu\n"
        "/rules — Community rules\n\n"
        "🛡 Automatic moderation:\n"
        "• Bad/profanity words\n"
        "• NSFW text\n"
        "• NSFW photos\n"
        "• GIF/animation scanning\n"
        "• GIF document scanning\n"
        "• Video scanning\n"
        "• Spam protection\n"
        "• Human verification"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu",
        ),
    ]]

    markup = InlineKeyboardMarkup(
        keyboard
    )

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=markup,
        )

    elif update.callback_query:

        await update.callback_query.message.edit_text(
            text,
            reply_markup=markup,
        )


# ============================================================
# RULES
# ============================================================

async def rules_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "📜 Community Guidelines\n\n"
        "1. 🚫 No spam or advertisements\n"
        "2. 🚫 No excessive profanity\n"
        "3. 🚫 No NSFW content\n"
        "4. 🤝 Respect other members\n"
        "5. 🛡 Follow verification requirements"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu",
        ),
    ]]

    markup = InlineKeyboardMarkup(
        keyboard
    )

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=markup,
        )

    elif update.callback_query:

        await update.callback_query.message.edit_text(
            text,
            reply_markup=markup,
        )


# ============================================================
# ADMIN PANEL
# ============================================================

async def admin_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "🛠 Admin Control Panel\n\n"
        "Bmax must be an administrator in the group.\n\n"
        "Required permission:\n"
        "• 🗑 Delete messages"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu",
        ),
    ]]

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# ABOUT
# ============================================================

async def about_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "ℹ️ About Bmax Bot\n\n"
        "Bmax is a Telegram community moderation "
        "and security utility with automated "
        "text and media protection."
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu",
        ),
    ]]

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    nudenet_status = (
        "Online"
        if nude_detector is not None
        else "Loading / unavailable"
    )

    text = (
        "🛡 Bmax Security Status\n\n"
        "• Core Engine: Online\n"
        "• Bad-Word Filter: Active\n"
        "• NSFW Text Filter: Active\n"
        f"• NSFW Image Detection: {nudenet_status}\n"
        "• GIF Scanning: Active\n"
        "• Video Scanning: Active\n"
        "• GIF Document Scanning: Active\n"
        "• Spam Protection: Active\n"
        "• Verification: Active"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu",
        ),
    ]]

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# FEATURES
# ============================================================

async def features_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "⚡ Feature Showcase\n\n"
        "🧹 Bad Word Protection\n"
        "🔞 NSFW Text Protection\n"
        "🖼 NSFW Image Detection\n"
        "🎞 Fast GIF Detection\n"
        "📁 GIF Document Detection\n"
        "🎥 Fast Video Detection\n"
        "🛡 Human Verification\n"
        "🚫 Spam Protection\n"
        "⚙️ Render Health Endpoint"
    )

    keyboard = [[
        InlineKeyboardButton(
            "« Back to Main Menu",
            callback_data="start_menu",
        ),
    ]]

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# SPAM CHECK
# ============================================================

def is_spamming(
    user_id,
):

    if not user_id:
        return False

    now = time.time()

    times = user_message_times.get(
        user_id,
        [],
    )

    times = [
        timestamp
        for timestamp in times
        if now - timestamp <= SPAM_WINDOW
    ]

    times.append(now)

    user_message_times[
        user_id
    ] = times

    return len(times) > SPAM_LIMIT


# ============================================================
# NEW MEMBER VERIFICATION
# ============================================================

async def handle_new_members(
    message,
    context,
):

    if not message.new_chat_members:
        return False

    for member in message.new_chat_members:

        # Don't verify the bot itself.
        if member.id == context.bot.id:
            continue

        welcome_text = (
            f"Welcome, {member.first_name}! 👋\n\n"
            "Please verify that you're human "
            "before chatting in this group."
        )

        try:

            sent_msg = await message.reply_text(
                welcome_text
            )

            payload = (
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
                        f"?start={payload}"
                    ),
                ),
            ]]

            await sent_msg.edit_text(
                welcome_text,
                reply_markup=InlineKeyboardMarkup(
                    keyboard
                ),
            )

        except Exception:
            logger.exception(
                "Could not create verification message."
            )

    return True


# ============================================================
# PRIVATE VERIFICATION
# ============================================================

async def handle_private_verification(
    message,
    context,
):

    user_id = (
        message.from_user.id
        if message.from_user
        else None
    )

    if not user_id:
        return False

    verification = pending_verifications.get(
        user_id
    )

    if not verification:
        return False

    # Expire challenges after 10 minutes.
    if (
        time.time()
        - verification["created_at"]
        > 600
    ):

        del pending_verifications[user_id]

        await message.reply_text(
            "⌛ Your verification expired.\n"
            "Please request a new verification."
        )

        return True

    user_text = (
        message.text
        or ""
    ).strip()

    expected_code = verification["code"]

    if user_text == expected_code:

        chat_id = verification["chat_id"]

        if user_id not in verified_users:

            verified_users[user_id] = set()

        verified_users[user_id].add(
            chat_id
        )

        target_message_id = verification.get(
            "message_id"
        )

        del pending_verifications[
            user_id
        ]

        await message.reply_text(
            "✅ Verification successful!\n\n"
            "You're now verified and ready "
            "to chat in the group."
        )

        if target_message_id:

            try:

                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=target_message_id,
                )

            except Exception as e:

                logger.warning(
                    "Could not delete verification message: %s",
                    e,
                )

        return True

    await message.reply_text(
        "❌ Incorrect code.\n\n"
        "Please enter the verification code "
        "shown in the challenge."
    )

    return True


# ============================================================
# SECURITY GUARD
# ============================================================

async def security_guard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    message = update.message

    # --------------------------------------------------------
    # NEW MEMBERS
    # --------------------------------------------------------

    if message.new_chat_members:

        await handle_new_members(
            message,
            context,
        )

        return

    # --------------------------------------------------------
    # IGNORE BOT
    # --------------------------------------------------------

    if (
        message.from_user
        and message.from_user.id
        == context.bot.id
    ):
        return

    # --------------------------------------------------------
    # PRIVATE VERIFICATION
    # --------------------------------------------------------

    if (
        message.chat.type == "private"
        and message.from_user
        and message.from_user.id
        in pending_verifications
    ):

        await handle_private_verification(
            message,
            context,
        )

        return

    # --------------------------------------------------------
    # ONLY MODERATE GROUPS
    # --------------------------------------------------------

    if message.chat.type not in (
        "group",
        "supergroup",
    ):

        return

    user_id = (
        message.from_user.id
        if message.from_user
        else None
    )

    # --------------------------------------------------------
    # SPAM
    # --------------------------------------------------------

    if is_spamming(user_id):

        await delete_message_safely(
            message,
            "spam/rate limit",
        )

        return

    # --------------------------------------------------------
    # TEXT / CAPTION
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
            f"blocked word: {blocked_word}",
        )

        return

    # --------------------------------------------------------
    # PHOTO
    # --------------------------------------------------------

    if message.photo:

        is_nsfw, result = await check_photo(
            message
        )

        if is_nsfw:

            await delete_message_safely(
                message,
                f"NSFW photo: {result}",
            )

            return

    # --------------------------------------------------------
    # ANIMATION
    # --------------------------------------------------------

    if message.animation:

        is_nsfw, result = await check_animation(
            message
        )

        if is_nsfw:

            await delete_message_safely(
                message,
                f"NSFW animation: {result}",
            )

            return

    # --------------------------------------------------------
    # VIDEO
    # --------------------------------------------------------

    if message.video:

        is_nsfw, result = await check_video(
            message
        )

        if is_nsfw:

            await delete_message_safely(
                message,
                f"NSFW video: {result}",
            )

            return

    # --------------------------------------------------------
    # GIF DOCUMENT
    # --------------------------------------------------------

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
                    f"NSFW GIF document: {result}",
                )

                return


# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    try:

        await query.answer()

    except Exception:
        pass

    if query.data == "rules":

        await rules_command(
            update,
            context,
        )

    elif query.data == "help":

        await help_command(
            update,
            context,
        )

    elif query.data == "admin_panel":

        await admin_panel(
            update,
            context,
        )

    elif query.data == "about":

        await about_command(
            update,
            context,
        )

    elif query.data == "status":

        await status_command(
            update,
            context,
        )

    elif query.data == "features":

        await features_command(
            update,
            context,
        )

    elif query.data == "start_menu":

        await start(
            update,
            context,
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error,
    )


# ============================================================
# STARTUP TASK
# ============================================================

async def post_init(
    application,
):

    logger.info(
        "Telegram application initialized."
    )

    # Initialize NudeNet after the Telegram application
    # has successfully initialized.
    asyncio.create_task(
        ensure_nudenet()
    )


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info(
        "Starting Bmax..."
    )

    # --------------------------------------------------------
    # RENDER WEB SERVER
    # --------------------------------------------------------

    keep_alive()

    # --------------------------------------------------------
    # TELEGRAM APPLICATION
    # --------------------------------------------------------

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "rules",
            rules_command,
        )
    )

    # --------------------------------------------------------
    # BUTTONS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            button_handler,
        )
    )

    # --------------------------------------------------------
    # ALL NON-COMMAND MESSAGES
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            security_guard,
        )
    )

    # --------------------------------------------------------
    # ERROR HANDLER
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    # --------------------------------------------------------
    # POLLING
    # --------------------------------------------------------

    logger.info(
        "Bmax Telegram bot is starting polling..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
