import os
import re
import logging
import threading
import asyncio
import random
import tempfile
import shutil
import time
from typing import Optional

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
# NUDE NET
# ============================================================

nude_detector = None

nude_detector_init_lock = asyncio.Lock()
nudenet_scan_lock = asyncio.Lock()


NSFW_LABELS = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "MALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
}

# Lower = more sensitive, but more false positives.
NSFW_SCORE_THRESHOLD = 0.50


# ============================================================
# FAST MEDIA SETTINGS
# ============================================================

# Fewer frames = faster moderation.
FAST_FRAME_COUNT = 4

# Keep frames small so NudeNet inference is faster.
FRAME_WIDTH = 384

# JPEG quality.
FRAME_QUALITY = "6"

# Maximum Telegram media size downloaded by the bot.
MAX_MEDIA_BYTES = 50 * 1024 * 1024

# Don't spend huge amounts of CPU on extremely long videos.
MAX_SCAN_DURATION = 300


# ============================================================
# PROFANITY / NSFW WORD FILTER
# ============================================================

BLOCKED_WORDS = {
    # profanity
    "fuck",
    "fucking",
    "fucked",
    "fucker",
    "fuckers",
    "motherfuck",
    "motherfucker",
    "motherfuckers",
    "shit",
    "shitty",
    "bullshit",
    "bitch",
    "bitches",
    "bitching",
    "asshole",
    "assholes",
    "bastard",
    "bastards",
    "jackass",
    "jackasses",
    "dickhead",
    "dickheads",

    # sexual / NSFW
    "porn",
    "porno",
    "pornography",
    "pornographic",
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
    "blowjobs",
    "handjob",
    "handjobs",
    "masturbation",
    "masturbate",
    "masturbating",
    "orgasm",
    "orgasms",
    "cum",
    "cumming",
    "dildo",
    "dildos",
    "pussy",
    "pussies",
    "dick",
    "dicks",
    "cock",
    "cocks",
    "boob",
    "boobs",
    "tits",
    "titty",
    "erotic",
    "erotica",
    "explicit",
    "lewd",
    "sexcam",
    "sexcams",
    "sexchat",
    "sexchats",
    "onlyfans",
    "anal",
    "vagina",
    "vaginas",
    "penis",
    "penises",
    "genital",
    "genitals",
    "intercourse",
    "prostitute",
    "prostitution",
    "pornstar",
    "pornstars",
    "pornhub",
    "xvideos",
    "xnxx",
}


DISGUISED_WORDS = {
    "f1uck": "fuck",
    "f4ck": "fuck",
    "sh1t": "shit",
    "sh!t": "shit",
    "b1tch": "bitch",
    "b!tch": "bitch",
    "a55hole": "asshole",
    "assh0le": "asshole",
    "p0rn": "porn",
    "p0rno": "porno",
    "p0rn0": "porno",
    "s3x": "sex",
    "s3xy": "sexy",
    "n4ked": "naked",
    "n00d": "nude",
    "n00des": "nudes",
    "nud3": "nude",
    "n5fw": "nsfw",
    "h3ntai": "hentai",
    "c0ck": "cock",
    "c0cks": "cocks",
    "d1ck": "dick",
    "d!ck": "dick",
    "b00b": "boob",
    "b00bs": "boobs",
    "t1t": "tits",
    "t1ts": "tits",
    "cvm": "cum",
    "v4gina": "vagina",
    "v4gin4": "vagina",
    "p3nis": "penis",
    "bl0wj0b": "blowjob",
    "masturb4tion": "masturbation",
    "0nlyfans": "onlyfans",
}


# ============================================================
# VERIFICATION
# ============================================================

pending_verifications = {}
verified_users = {}


# ============================================================
# SPAM
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
        logger.info("Loading NudeNet...")

        nude_detector = NudeDetector()

        logger.info(
            "NudeNet loaded successfully."
        )

        return True

    except Exception:
        logger.exception(
            "Could not initialize NudeNet."
        )

        nude_detector = None

        return False


async def ensure_nudenet():

    global nude_detector

    if nude_detector is not None:
        return True

    async with nude_detector_init_lock:

        if nude_detector is not None:
            return True

        return await asyncio.to_thread(
            initialize_nudenet
        )


# ============================================================
# NUDE NET IMAGE SCAN
# ============================================================

def nudenet_scan_sync(
    image_bytes: bytes,
):

    global nude_detector

    if nude_detector is None:
        return None

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False,
        ) as file:

            file.write(image_bytes)
            temp_path = file.name

        detections = nude_detector.detect(
            temp_path
        )

        if not detections:
            return None

        best = None

        for detection in detections:

            label = str(
                detection.get(
                    "class",
                    "",
                )
            ).upper()

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
                    best is None
                    or score > best["score"]
                ):

                    best = {
                        "label": label,
                        "score": score,
                    }

        return best

    except Exception:
        logger.exception(
            "NudeNet scan error."
        )

        return None

    finally:

        if temp_path:

            try:
                os.remove(temp_path)
            except Exception:
                pass


async def scan_image(
    image_bytes: bytes,
):

    if not image_bytes:
        return None

    if not await ensure_nudenet():
        return None

    # Only one ONNX inference at a time.
    # This is much more stable on small Render instances.
    async with nudenet_scan_lock:

        return await asyncio.to_thread(
            nudenet_scan_sync,
            image_bytes,
        )


# ============================================================
# FFMPEG
# ============================================================

def ffmpeg_available():

    return (
        shutil.which("ffmpeg") is not None
        and shutil.which("ffprobe") is not None
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

        stdout, _ = await process.communicate()

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

        return min(
            duration,
            MAX_SCAN_DURATION,
        )

    except Exception:
        return None


# ============================================================
# FAST FRAME TIMESTAMPS
# ============================================================

def get_fast_timestamps(
    duration: Optional[float],
):

    if not duration or duration <= 0:
        return [0]

    if duration <= 2:
        return [
            0,
            duration / 2,
        ]

    if duration <= 8:
        return [
            0,
            duration * 0.35,
            duration * 0.70,
            duration * 0.95,
        ]

    # For a 60 second GIF:
    #
    # 0s
    # 20s
    # 40s
    # 57s
    #
    # This avoids waiting for the whole GIF to be decoded
    # before starting the first AI scan.

    return [
        0,
        duration * 0.33,
        duration * 0.66,
        duration * 0.95,
    ]


# ============================================================
# EXTRACT FRAME
# ============================================================

async def extract_frame(
    media_path,
    timestamp,
    output_path,
):

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",

        # Fast seeking.
        "-ss",
        str(timestamp),

        "-i",
        media_path,

        "-frames:v",
        "1",

        "-vf",
        f"scale={FRAME_WIDTH}:-2",

        "-q:v",
        FRAME_QUALITY,

        output_path,
    ]

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    _, stderr = await process.communicate()

    if process.returncode != 0:

        logger.debug(
            "Frame extraction error: %s",
            stderr.decode(
                errors="ignore"
            )[-300:],
        )

        return False

    return os.path.exists(
        output_path
    )


# ============================================================
# SCAN ONE FRAME
# ============================================================

async def scan_frame(
    frame_path,
):

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
            "Could not scan frame."
        )

        return None


# ============================================================
# FAST MEDIA SCANNER
# ============================================================

async def scan_media_fast(
    media_bytes: bytes,
    extension=".mp4",
):

    if not media_bytes:
        return False, None

    if len(media_bytes) > MAX_MEDIA_BYTES:

        logger.warning(
            "Media exceeds 50 MB."
        )

        return False, None

    if not ffmpeg_available():

        logger.error(
            "FFmpeg/FFprobe is not installed."
        )

        return False, None

    work_dir = tempfile.mkdtemp(
        prefix="bmax_fast_"
    )

    media_path = os.path.join(
        work_dir,
        f"media{extension}",
    )

    try:

        with open(
            media_path,
            "wb",
        ) as file:

            file.write(media_bytes)

        duration = await get_media_duration(
            media_path
        )

        timestamps = get_fast_timestamps(
            duration
        )

        logger.info(
            "Fast scan: %.2f seconds, %d frames.",
            duration or 0,
            len(timestamps),
        )

        # ====================================================
        # IMPORTANT:
        #
        # Frames are extracted and scanned ONE AT A TIME.
        #
        # As soon as one frame is NSFW, we return immediately.
        # We do NOT wait for the remaining frames.
        # ====================================================

        for index, timestamp in enumerate(
            timestamps,
            start=1,
        ):

            frame_path = os.path.join(
                work_dir,
                f"frame_{index}.jpg",
            )

            logger.info(
                "Extracting frame %d/%d at %.2fs",
                index,
                len(timestamps),
                timestamp,
            )

            extracted = await extract_frame(
                media_path,
                timestamp,
                frame_path,
            )

            if not extracted:
                continue

            result = await scan_frame(
                frame_path
            )

            # =================================================
            # POP!
            #
            # The caller can delete the Telegram message
            # immediately after this returns.
            # =================================================

            if result:

                logger.warning(
                    "NSFW FOUND immediately: %s",
                    result,
                )

                return True, result

        return False, None

    except Exception:
        logger.exception(
            "Fast media scan failed."
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

    size = getattr(
        telegram_file,
        "file_size",
        None,
    )

    if not size:
        return False

    return size > MAX_MEDIA_BYTES


# ============================================================
# PHOTO
# ============================================================

async def check_photo(
    message,
):

    try:

        telegram_file = await message.photo[-1].get_file()

        if telegram_file_too_large(
            telegram_file
        ):

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

        telegram_file = await message.animation.get_file()

        if telegram_file_too_large(
            telegram_file
        ):

            return False, None

        logger.info(
            "Downloading GIF/animation..."
        )

        media_bytes = await telegram_file.download_as_bytearray()

        logger.info(
            "GIF/animation downloaded."
        )

        return await scan_media_fast(
            bytes(media_bytes),
            ".mp4",
        )

    except Exception:
        logger.exception(
            "Animation scan failed."
        )

        return False, None


# ============================================================
#
