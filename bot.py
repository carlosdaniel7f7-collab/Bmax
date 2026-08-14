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

# Fast scan:
# Instead of scanning many frames, use only 6 representative
# frames for GIFs/videos.

MEDIA_FRAME_COUNT = 6

# Very short media still gets 6 frames.
MIN_MEDIA_FRAMES = 6

# Maximum extraction rate.
MAX_FPS = 1

# Resize frames before NudeNet.
# This makes the AI scan considerably faster.
FRAME_WIDTH = 480

# JPEG quality.
FRAME_QUALITY = "5"

# Number of frames NudeNet can process at the same time.
# 3 is a reasonable value for a small Render instance.
SCAN_CONCURRENCY = 3


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
            score = float(
                detection.get("score", 0)
            )

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

        with open(
            frame_path,
            "rb"
        ) as file:

            image_bytes = file.read()

        return await scan_image(
            image_bytes
        )

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

    if duration <= 2:
        return MIN_MEDIA_FRAMES

    return MEDIA_FRAME_COUNT


# ============================================================
# PARALLEL FRAME SCANNING
# ============================================================

async def scan_frames_parallel(frame_files):

    semaphore = asyncio.Semaphore(
        SCAN_CONCURRENCY
    )

    async def scan_one(index, frame_path):

        async with semaphore:

            logger.info(
                "Scanning frame %d/%d...",
                index,
                len(frame_files)
            )

            result = await scan_frame_file(
                frame_path
            )

            return index, result

    tasks = [
        asyncio.create_task(
            scan_one(
                index,
                frame_path
            )
        )
        for index, frame_path in enumerate(
            frame_files,
            start=1
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
                    len(frame_files)
                )

                # Cancel remaining scans.
                for task in tasks:

                    if not task.done():
                        task.cancel()

                await asyncio.gather(
                    *tasks,
                    return_exceptions=True
                )

                return True, result

        return False, None

    except Exception as e:

        for task in tasks:

            if not task.done():
                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True
        )

        raise e


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
            "FAST SCAN: approximately %d frames.",
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
                f"fps={fps:.4f},"
                f"scale={FRAME_WIDTH}:-1"
            )

        else:

            filter_value = (
                f"fps={MAX_FPS},"
                f"scale={FRAME_WIDTH}:-1"
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

        logger.info(
            "Extracting frames with FFmpeg..."
        )

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
        # PARALLEL SCAN
        # ----------------------------------------------------

        logger.info(
            "Starting parallel NudeNet scan "
            "(concurrency=%d)...",
            SCAN_CONCURRENCY
        )

        is_nsfw, result = await scan_frames_parallel(
            frame_files
        )

        if is_nsfw:

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
            "Animation downloaded. "
            "Starting FAST NSFW scan..."
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

        logger.info(
            "Video downloaded. "
            "Starting FAST NSFW scan..."
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

        logger.info(
            "GIF downloaded. "
            "Starting FAST NSFW scan..."
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
# =================================================
