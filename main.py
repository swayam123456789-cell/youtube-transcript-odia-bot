import asyncio
import logging
import os
import re
from io import BytesIO
from urllib.parse import urlparse, parse_qs

import yt_dlp
from deep_translator import GoogleTranslator
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters
)
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound, TranscriptsDisabled, VideoUnavailable
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO")
)
log = logging.getLogger("youtube-transcript-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
MAX_SECONDS = 90 * 60
CHUNK_CHARS = 3500

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")
if not BASE_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL environment variable is missing.")

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def get_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        video_id = None
        if host in ("youtu.be", "www.youtu.be"):
            video_id = parsed.path.strip("/").split("/")[0]
        elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [None])[0]
            else:
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live"):
                    video_id = parts[1]
        return video_id if video_id and VIDEO_ID_RE.fullmatch(video_id) else None
    except Exception:
        return None


def get_video_info(url: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 20,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def fetch_transcript(video_id: str):
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)
    available = list(transcript_list)
    if not available:
        raise NoTranscriptFound(video_id, ["or", "hi", "en"], [])

    # Prefer an Odia transcript if present, otherwise Hindi, then English,
    # then any available transcript.
    preferred = ("or", "hi", "en")
    chosen = None
    for code in preferred:
        chosen = next((t for t in available if t.language_code == code), None)
        if chosen:
            break
    if chosen is None:
        chosen = available[0]

    fetched = chosen.fetch()
    snippets = []
    for item in fetched:
        text = (getattr(item, "text", "") or "").replace("\n", " ").strip()
        if text:
            snippets.append({
                "start": float(getattr(item, "start", 0.0)),
                "duration": float(getattr(item, "duration", 0.0)),
                "text": text,
            })
    return chosen.language, chosen.language_code, snippets


def split_text(text: str, max_chars: int = CHUNK_CHARS):
    # Split at sentence boundaries where possible; never send huge requests.
    words = text.split()
    chunks, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def translate_to_odia(text: str) -> str:
    translator = GoogleTranslator(source="auto", target="or")
    translated = []
    for chunk in split_text(text):
        translated.append(translator.translate(chunk) or chunk)
    return "\n".join(translated)


def format_timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02}:{minutes:02}:{secs:02},000"


def make_txt(snippets, translated_text=None) -> str:
    if translated_text is not None:
        return translated_text.strip() + "\n"
    return "\n".join(s["text"] for s in snippets).strip() + "\n"


def make_srt(snippets, translated_lines=None) -> str:
    blocks = []
    if translated_lines is not None:
        # Translation is paragraph-level, so preserve original timing and
        # use translated paragraphs only if the count can be aligned safely.
        texts = translated_lines
        if len(texts) != len(snippets):
            texts = [s["text"] for s in snippets]
    else:
        texts = [s["text"] for s in snippets]
    for index, (snippet, text) in enumerate(zip(snippets, texts), start=1):
        start = max(0.0, snippet["start"])
        end = max(start + 0.5, start + snippet["duration"])
        def stamp(value):
            millis = int(round((value - int(value)) * 1000))
            whole = int(value)
            h, rem = divmod(whole, 3600)
            m, s = divmod(rem, 60)
            return f"{h:02}:{m:02}:{s:02},{millis:03}"
        blocks.append(
            f"{index}\n{stamp(start)} --> {stamp(end)}\n{text.strip()}\n"
        )
    return "\n".join(blocks) + "\n"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "ନମସ୍କାର! 👋\n\n"
        "YouTube ଭିଡିଓ ଲିଙ୍କ୍ ପଠାନ୍ତୁ।\n"
        "ସର୍ବାଧିକ ଭିଡିଓ ଅବଧି: ୯୦ ମିନିଟ୍।\n\n"
        "ସମର୍ଥିତ ଭାଷା: ହିନ୍ଦୀ, ଇଂରାଜୀ ଓ ଓଡ଼ିଆ।\n"
        "Transcript ଉପଲବ୍ଧ ଥିଲେ ହିଁ ଏହା ବାହାର କରିପାରିବ।"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ବ୍ୟବହାର:\n"
        "୧. YouTube ଭିଡିଓ ଲିଙ୍କ୍ ପଠାନ୍ତୁ।\n"
        "୨. Transcript କିମ୍ବା ଓଡ଼ିଆ ଅନୁବାଦ ବାଛନ୍ତୁ।\n"
        "୩. TXT କିମ୍ବା SRT ଫାଇଲ୍ ଡାଉନଲୋଡ୍ କରନ୍ତୁ।\n\n"
        "ସୀମା: ୯୦ ମିନିଟ୍। ଭିଡିଓରେ ଉପଲବ୍ଧ subtitles/transcript ଦରକାର।"
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = (update.message.text or "").strip()
    video_id = get_video_id(url)
    if not video_id:
        await update.message.reply_text(
            "ଦୟାକରି ଏକ ସଠିକ୍ YouTube ଭିଡିଓ ଲିଙ୍କ୍ ପଠାନ୍ତୁ।"
        )
        return

    status = await update.message.reply_text("🔎 ଭିଡିଓ ଯାଞ୍ଚ କରୁଛି…")
    try:
        # yt-dlp can fail against YouTube even when captions are accessible.
        # Continue to transcript lookup and enforce the 90-minute limit using
        # transcript timestamps if metadata duration is unavailable.
        duration = None
        title = f"YouTube video ({video_id})"
        try:
            info = await asyncio.to_thread(get_video_info, url)
            duration = info.get("duration")
            title = info.get("title", title)
        except Exception:
            log.exception("yt-dlp metadata lookup failed; falling back to transcript timestamps")

        if duration is not None and duration > MAX_SECONDS:
            await status.edit_text(
                "❌ ଏହି ଭିଡିଓ ୯୦ ମିନିଟ୍‌ରୁ ଅଧିକ।\n"
                "ଦୟାକରି ୯୦ ମିନିଟ୍ କିମ୍ବା ତାଠାରୁ କମ୍ ଭିଡିଓ ପଠାନ୍ତୁ।"
            )
            return

        context.user_data["video_id"] = video_id
        context.user_data["video_url"] = url
        context.user_data["video_title"] = title
        context.user_data["video_duration"] = duration
        duration_label = f"{duration // 60} ମିନିଟ୍" if duration is not None else "Transcript ରୁ ଯାଞ୍ଚ ହେବ"
        await status.edit_text(
            f"✅ ଭିଡିଓ ଲିଙ୍କ୍ ଗ୍ରହଣ କରାଗଲା।\n\n🎬 {title}\n"
            f"⏱️ ଅବଧି: {duration_label}\n\nକ'ଣ କରିବାକୁ ଚାହୁଁଛନ୍ତି?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📄 ମୂଳ Transcript", callback_data="original")],
                [InlineKeyboardButton("✍️ ଓଡ଼ିଆକୁ ଅନୁବାଦ", callback_data="odia")],
            ])
        )
    except Exception:
        log.exception("Video link processing failed")
        await status.edit_text(
            "ଭିଡିଓ ଲିଙ୍କ୍ ପ୍ରୋସେସ୍ କରିହେଲା ନାହିଁ। କିଛି ସମୟ ପରେ ପୁଣି ଚେଷ୍ଟା କରନ୍ତୁ।"
        )


async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    video_id = context.user_data.get("video_id")
    if not video_id:
        await query.edit_message_text("ପ୍ରଥମେ ପୁଣି YouTube ଲିଙ୍କ୍ ପଠାନ୍ତୁ।")
        return

    action = query.data
    await query.edit_message_text("⏳ Transcript ଆଣୁଛି… ଦୟାକରି ଅପେକ୍ଷା କରନ୍ତୁ।")
    try:
        language, lang_code, snippets = await asyncio.to_thread(fetch_transcript, video_id)
        if not snippets:
            await query.message.reply_text("ଏହି ଭିଡିଓରେ Transcript ମିଳିଲା ନାହିଁ।")
            return

        # If yt-dlp could not read the duration, infer it from the last
        # caption timestamp before sending any transcript to the user.
        transcript_end = max(
            (s["start"] + s["duration"] for s in snippets),
            default=0
        )
        if transcript_end > MAX_SECONDS:
            await query.message.reply_text(
                "❌ ଏହି ଭିଡିଓ ୯୦ ମିନିଟ୍‌ରୁ ଅଧିକ।\n"
                "ଦୟାକରି ୯୦ ମିନିଟ୍ କିମ୍ବା ତାଠାରୁ କମ୍ ଭିଡିଓ ପଠାନ୍ତୁ।"
            )
            return

        original_text = "\n".join(s["text"] for s in snippets)
        if action == "odia":
            await query.message.reply_text("✍️ ଓଡ଼ିଆକୁ ଅନୁବାଦ କରୁଛି…")
            translated = await asyncio.to_thread(translate_to_odia, original_text)
            txt_content = make_txt(snippets, translated)
            # Keep SRT timestamps intact by translating each caption in chunks
            # individually, avoiding loss of timestamp alignment.
            translated_lines = await asyncio.to_thread(
                lambda: [
                    GoogleTranslator(source="auto", target="or").translate(s["text"]) or s["text"]
                    for s in snippets
                ]
            )
            srt_content = make_srt(snippets, translated_lines)
            label = "ଓଡ଼ିଆ"
        else:
            txt_content = make_txt(snippets)
            srt_content = make_srt(snippets)
            label = f"ମୂଳ ({language})"

        title = context.user_data.get("video_title", "transcript")
        safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", title)[:45].strip("_") or "transcript"
        txt_bytes = BytesIO(txt_content.encode("utf-8"))
        txt_bytes.name = f"{safe_title}_{label}_transcript.txt"
        srt_bytes = BytesIO(srt_content.encode("utf-8"))
        srt_bytes.name = f"{safe_title}_{label}_subtitles.srt"

        await query.message.reply_text(
            f"✅ Transcript ପ୍ରସ୍ତୁତ!\nଭାଷା: {label}\n"
            f"ମୂଳ subtitle language code: {lang_code}"
        )
        await query.message.reply_document(document=txt_bytes, caption="📄 TXT Transcript")
        await query.message.reply_document(document=srt_bytes, caption="🎬 SRT Subtitles")
    except (TranscriptsDisabled, NoTranscriptFound):
        await query.message.reply_text(
            "❌ ଏହି ଭିଡିଓରେ ଉପଲବ୍ଧ Transcript/Subtitles ମିଳିଲା ନାହିଁ। "
            "ଏହି ପ୍ରାରମ୍ଭିକ ସଂସ୍କରଣ Audio Download କରି Speech-to-Text କରେ ନାହିଁ।"
        )
    except VideoUnavailable:
        await query.message.reply_text("❌ ଭିଡିଓଟି ଉପଲବ୍ଧ ନାହିଁ କିମ୍ବା ପ୍ରବେଶ ସୀମିତ ଅଛି।")
    except Exception:
        log.exception("Transcript processing failed")
        await query.message.reply_text(
            "❌ Transcript ପ୍ରସ୍ତୁତ କରିବାରେ ସମସ୍ୟା ହେଲା। କିଛି ସମୟ ପରେ ପୁଣି ଚେଷ୍ଟା କରନ୍ତୁ।"
        )


async def post_init(app: Application):
    await app.bot.set_my_commands([
        ("start", "Bot ଆରମ୍ଭ କରନ୍ତୁ"),
        ("help", "ସାହାଯ୍ୟ"),
    ])


def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(handle_action, pattern="^(original|odia)$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    webhook_path = BOT_TOKEN.split(":")[0]  # non-secret path component
    webhook_url = f"{BASE_URL}/{webhook_path}"
    log.info("Starting webhook on port %s", PORT)
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=webhook_path,
        webhook_url=webhook_url,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
        
