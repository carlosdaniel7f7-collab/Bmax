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

nude_detector = None
nude_detector_lock = asyncio.Lock()


# ============================================================
# NSFW SETTINGS (TUNED FOR INSTANT AGGRESSIVE TRIPPED WIPING)
# ============================================================

NSFW_LABELS = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "MALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
}

# Lowered to 0.40 so explicit content trips the trigger instantly
NSFW_SCORE_THRESHOLD = 0.40


# ============================================================
# MEDIA SETTINGS (TUNED FOR LIGHTNING-FAST 1-SECOND EXECUTION)
# ============================================================

# Checked frames count per video/GIF (reduced to 2 for blazing fast checks)
MEDIA_FRAME_COUNT = 2

# Maximum extraction FPS
MAX_FPS = 1

# Smaller width = instant processing load on CPU
FRAME_WIDTH = 256

# Fast JPEG compression quality
FRAME_QUALITY = "5"

# Concurrency level for background frame evaluation
SCAN_CONCURRENCY = 4

# Maximum downloaded media size limit (50 MB)
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

pending_verifications = {}
verified_users = {}


# ============================================================
# RATE LIMIT STORAGE
# ============================================================

user_message_times = {}
SPAM_WINDOW = 8
SPAM_LIMIT = 8


# ============================================================
# NUDE NET INITIALIZATION
# ============================================================

def initialize_nudenet():
    global nude_detector
    try:
        logger.info("Initializing NudeNet...")
        detector = NudeDetector()
        nude_detector = detector
        logger.info("NudeNet NSFW detector initialized successfully.")
        return True
    except Exception:
        logger.exception("NudeNet initialization failed.")
        nude_detector = None
        return False


async def ensure_nudenet():
    global nude_detector
    if nude_detector is not None:
        return True
    async with nude_detector_lock:
        if nude_detector is not None:
            return True
        return await asyncio.to_thread(initialize_nudenet)


# ============================================================
# NUDE NET IMAGE SCANNER (WITH FAST MODE)
# ============================================================

def nudenet_scan(image_bytes: bytes):
    global nude_detector
    if nude_detector is None:
        return None

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
            temp_file.write(image_bytes)
            temp_path = temp_file.name

        detections = nude_detector.detect(temp_path, mode="fast")

        if not detections:
            return None

        best_detection = None
        for detection in detections:
            label = detection.get("class", "")
            try:
                score = float(detection.get("score", 0))
            except Exception:
                score = 0.0

            if label in NSFW_LABELS and score >= NSFW_SCORE_THRESHOLD:
                if best_detection is None or score > best_detection["score"]:
                    best_detection = {"label": label, "score": score}

        if best_detection:
            logger.warning("NSFW detected: %s %.3f", best_detection["label"], best_detection["score"])
            return best_detection

        return None
    except Exception:
        logger.exception("NudeNet scan failed.")
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
        return None
    return await asyncio.to_thread(nudenet_scan, image_bytes)


async def scan_frame_file(frame_path):
    try:
        with open(frame_path, "rb") as file:
            image_bytes = file.read()
        return await scan_image(image_bytes)
    except Exception:
        return None


def ffmpeg_available():
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# ============================================================
# PARALLEL FRAME SCANNING WITH INSTANT BREAKOUT
# ============================================================

async def scan_frames_parallel(frame_files):
    semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)

    async def scan_one(index, frame_path):
        async with semaphore:
            result = await scan_frame_file(frame_path)
            return index, result

    tasks = [
        asyncio.create_task(scan_one(index, frame_path))
        for index, frame_path in enumerate(frame_files, start=1)
    ]

    try:
        for completed_task in asyncio.as_completed(tasks):
            index, result = await completed_task
            if result:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                return True, result

        return False, None
    except Exception:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        return False, None


# ============================================================
# EXTRACT + SCAN MEDIA FAST PIPELINE
# ============================================================

async def extract_and_scan_media(media_bytes: bytes, extension=".mp4"):
    if not media_bytes or len(media_bytes) > MAX_MEDIA_BYTES:
        return False, None

    work_dir = tempfile.mkdtemp(prefix="bmax_media_")
    media_path = os.path.join(work_dir, f"media{extension}")
    frames_pattern = os.path.join(work_dir, "frame_%03d.jpg")

    try:
        with open(media_path, "wb") as file:
            file.write(media_bytes)

        if not ffmpeg_available():
            return False, None

        filter_value = f"fps={MAX_FPS},scale={FRAME_WIDTH}:-2"

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
            str(MEDIA_FRAME_COUNT),
            "-q:v",
            FRAME_QUALITY,
            frames_pattern,
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await process.communicate()
        if process.returncode != 0:
            return False, None

        frame_files = sorted(
            [
                os.path.join(work_dir, filename)
                for filename in os.listdir(work_dir)
                if filename.startswith("frame_") and filename.endswith(".jpg")
            ]
        )

        if not frame_files:
            return False, None

        return await scan_frames_parallel(frame_files)

    except Exception:
        return False, None
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def telegram_file_too_large(telegram_file):
    file_size = getattr(telegram_file, "file_size", None)
    if not file_size:
        return False
    return file_size > MAX_MEDIA_BYTES


async def check_photo(message):
    try:
        telegram_file = await message.photo[-1].get_file()
        if telegram_file_too_large(telegram_file):
            return False, None
        image_bytes = await telegram_file.download_as_bytearray()
        result = await scan_image(bytes(image_bytes))
        if result:
            return True, result
        return False, None
    except Exception:
        return False, None


async def check_animation(message):
    try:
        telegram_file = await message.animation.get_file()
        if telegram_file_too_large(telegram_file):
            return False, None
        media_bytes = await telegram_file.download_as_bytearray()
        return await extract_and_scan_media(bytes(media_bytes), extension=".mp4")
    except Exception:
        return False, None


async def check_video(message):
    try:
        telegram_file = await message.video.get_file()
        if telegram_file_too_large(telegram_file):
            return False, None
        media_bytes = await telegram_file.download_as_bytearray()
        return await extract_and_scan_media(bytes(media_bytes), extension=".mp4")
    except Exception:
        return False, None


async def check_gif_document(message):
    try:
        if not message.document:
            return False, None
        mime_type = (message.document.mime_type or "").lower()
        file_name = (message.document.file_name or "").lower()

        if mime_type != "image/gif" and not file_name.endswith(".gif"):
            return False, None

        telegram_file = await message.document.get_file()
        if telegram_file_too_large(telegram_file):
            return False, None
        media_bytes = await telegram_file.download_as_bytearray()
        return await extract_and_scan_media(bytes(media_bytes), extension=".gif")
    except Exception:
        return False, None


async def delete_message_safely(message, reason=""):
    try:
        await message.delete()
        logger.warning("MESSAGE DELETED: %s", reason)
        return True
    except Exception as e:
        logger.error("Could not delete message: %s", e)
        return False


def normalize_text(text: str):
    if not text:
        return ""
    text = text.lower()
    replacements = {
        "0": "o", "1": "i", "3": "e", "4": "a",
        "5": "s", "7": "t", "@": "a", "$": "s",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def contains_blocked_word(text: str):
    if not text:
        return None
    lowered = text.lower()
    for word in BLOCKED_WORDS:
        pattern = rf"(?<!\w){re.escape(word)}(?!\w)"
        if re.search(pattern, lowered):
            return word
    for disguised, original in DISGUISED_WORDS.items():
        if disguised in lowered:
            return original
    normalized = normalize_text(text)
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
    return "Bmax Bot is alive and running!"


@app.route("/health")
def health():
    return {
        "status": "ok",
        "nudenet": nude_detector is not None,
    }


def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def keep_alive():
    thread = threading.Thread(target=run_flask, daemon=True)
    thread.start()


def main_keyboard(bot_username):
    keyboard = [
        [InlineKeyboardButton("➕ Add Me to Your Group", url=f"https://t.me/{bot_username}?startgroup=true")],
        [InlineKeyboardButton("📢 Add Me to Your Channel", url=f"https://t.me/{bot_username}?startchannel=true")],
        [InlineKeyboardButton("🛠 Admin Control Panel", callback_data="admin_panel"), InlineKeyboardButton("📜 Community Rules", callback_data="rules")],
        [InlineKeyboardButton("❓ Help & Commands", callback_data="help"), InlineKeyboardButton("ℹ️ About Bmax", callback_data="about")],
        [InlineKeyboardButton("🛡 Security Status", callback_data="status"), InlineKeyboardButton("⚡ Feature Showcase", callback_data="features")],
        [InlineKeyboardButton("🌐 Official Support Community", url="https://t.me/Anime7p7")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user else None

    if context.args:
        arg = context.args[0]
        if arg.startswith("verify_"):
            if not user_id:
                return
            parts = arg.split("_")
            try:
                target_chat_id = int(parts[1])
            except (ValueError, IndexError):
                target_chat_id = None

            if not target_chat_id:
                if update.message:
                    await update.message.reply_text("❌ Invalid verification link.")
                return

            code = str(random.randint(1000, 9999))
            pending_verifications[user_id] = {
                "code": code,
                "chat_id": target_chat_id,
                "message_id": int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else None,
                "created_at": time.time(),
            }
            if update.message:
                await update.message.reply_text(
                    "🔐 Verification Challenge\n\nReply with the following number to prove you are human:\n\n" f"**{code}**",
                    parse_mode="Markdown",
                )
            return

    bot_username = context.bot.username
    welcome_text = (
        "🤖 Welcome to Bmax Ultimate Command Center!\n\n"
        "Heya! I'm Bmax — your moderation and community security bot.\n\n"
        "⚡ Features:\n• Anti-Spam & moderation\n• Bad-word filtering\n• NSFW photo detection\n"
        "• Fast GIF detection\n• GIF document detection\n• Fast video detection\n• Human verification\n\n📋 Select an option below:"
    )
    keyboard = main_keyboard(bot_username)

    try:
        if update.message:
            await update.message.reply_text(welcome_text, reply_markup=keyboard)
        elif update.callback_query:
            await update.callback_query.message.edit_text(welcome_text, reply_markup=keyboard)
    except Exception:
        logger.exception("Could not display main menu.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "❓ Bmax Command Reference\n\n/start — Main dashboard\n/help — Help menu\n/rules — Community rules"
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=markup)


async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📜 Community Guidelines\n\n1. 🚫 No spam or advertisements\n2. 🚫 No excessive profanity\n3. 🚫 No NSFW content\n4. 🤝 Respect other members"
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=markup)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🛠 Admin Control Panel\n\nBmax must be an administrator in the group with delete message permissions."
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "ℹ️ About Bmax Bot\n\nBmax is a Telegram community moderation utility with lightning-fast text and media protection."
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nudenet_status = "Online" if nude_detector is not None else "Loading / unavailable"
    text = f"🛡 Bmax Security Status\n\n• Core Engine: Online\n• Bad-Word Filter: Active\n• NSFW Image Detection: {nudenet_status}\n• GIF/Video Scanning: Active"
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def features_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "⚡ Feature Showcase\n\n🧹 Bad Word Protection\n🔞 NSFW Text Protection\n🖼 Lightning-Fast NSFW Image & GIF Detection\n🎥 Instant Video Protection"
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="start_menu")]]
    await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


def is_spamming(user_id):
    if not user_id:
        return False
    now = time.time()
    times = user_message_times.get(user_id, [])
    times = [t for t in times if now - t <= SPAM_WINDOW]
    times.append(now)
    user_message_times[user_id] = times
    return len(times) > SPAM_LIMIT


async def handle_new_members(message, context):
    if not message.new_chat_members:
        return False
    for member in message.new_chat_members:
        if member.id == context.bot.id:
            continue
        welcome_text = f"Welcome, {member.first_name}! 👋\nPlease verify that you're human before chatting."
        try:
            sent_msg = await message.reply_text(welcome_text)
            payload = f"verify_{message.chat_id}_{sent_msg.message_id}"
            keyboard = [[InlineKeyboardButton("🛡 Verify you're human", url=f"https://t.me/{context.bot.username}?start={payload}")]]
            await sent_msg.edit_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            pass
    return True


async def handle_private_verification(message, context):
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return False
    verification = pending_verifications.get(user_id)
    if not verification:
        return False

    if time.time() - verification["created_at"] > 600:
        del pending_verifications[user_id]
        await message.reply_text("⌛ Your verification expired.")
        return True

    if (message.text or "").strip() == verification["code"]:
        chat_id = verification["chat_id"]
        if user_id not in verified_users:
            verified_users[user_id] = set()
        verified_users[user_id].add(chat_id)
        target_message_id = verification.get("message_id")
        del pending_verifications[user_id]

        await message.reply_text("✅ Verification successful! You can now chat in the group.")
        if target_message_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=target_message_id)
            except Exception:
                pass
        return True

    await message.reply_text("❌ Incorrect code.")
    return True


# ============================================================
# SECURITY GUARD (LIGHTNING FAST MODERATION ROUTINE)
# ============================================================

async def security_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    message = update.message

    if message.new_chat_members:
        await handle_new_members(message, context)
        return

    if message.from_user and message.from_user.id == context.bot.id:
        return

    if message.chat.type == "private" and message.from_user and message.from_user.id in pending_verifications:
        await handle_private_verification(message, context)
        return

    if message.chat.type not in ("group", "supergroup"):
        return

    user_id = message.from_user.id if message.from_user else None

    if is_spamming(user_id):
        await delete_message_safely(message, "spam/rate limit")
        return

    text_content = message.text or message.caption or ""
    blocked_word = contains_blocked_word(text_content)
    if blocked_word:
        await delete_message_safely(message, f"blocked word: {blocked_word}")
        return

    # Instant Media Filtering Checks
    if message.photo:
        is_nsfw, result = await check_photo(message)
        if is_nsfw:
            await delete_message_safely(message, f"NSFW photo: {result}")
            return

    elif message.animation:
        is_nsfw, result = await check_animation(message)
        if is_nsfw:
            await delete_message_safely(message, f"NSFW animation: {result}")
            return

    elif message.video:
        is_nsfw, result = await check_video(message)
        if is_nsfw:
            await delete_message_safely(message, f"NSFW video: {result}")
            return

    elif message.document:
        is_nsfw, result = await check_gif_document(message)
        if is_nsfw:
            await delete_message_safely(message, f"NSFW GIF document: {result}")
            return


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    mapping = {
        "rules": rules_command,
        "help": help_command,
        "admin_panel": admin_panel,
        "about": about_command,
        "status": status_command,
        "features": features_command,
        "start_menu": start,
    }

    if query.data in mapping:
        await mapping[query.data](update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update:", exc_info=context.error)


async def post_init(application):
    logger.info("Telegram application initialized.")
    asyncio.create_task(ensure_nudenet())


def main():
    logger.info("Starting Bmax...")
    keep_alive()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("rules", rules_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, security_guard))
    application.add_error_handler(error_handler)

    logger.info("Bmax Telegram bot is starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
