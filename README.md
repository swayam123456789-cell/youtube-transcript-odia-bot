# YouTube Transcript Bot (Odia)

Telegram bot for extracting available YouTube captions/transcripts for videos up to 90 minutes, with an Odia translation option and TXT/SRT outputs.

## Important limitations
- It uses captions/transcripts available from YouTube. This starter version does **not** download video/audio or run speech-to-text when captions are unavailable.
- YouTube metadata/transcript access can fail for private, restricted, age-gated, or temporarily blocked videos.
- Odia translation uses GoogleTranslator via `deep-translator`; it is an unofficial service and may be rate-limited.
- Render Free has limited RAM and may sleep. Long transcript/translation jobs may fail or take time.
- The 90-minute check depends on yt-dlp being able to read the video's metadata.

## Deploy to Render
1. Create a **new GitHub repository**. Do not overwrite the existing SwayamQuizBot repository.
2. Upload all files from this folder.
3. In Render, choose **New + → Web Service** and connect this new repository.
4. Set Runtime to Python if asked. Build command: `pip install -r requirements.txt`; Start command: `python main.py`.
5. Add environment variable `BOT_TOKEN` with the token from BotFather.
6. After deployment, copy the Render service URL into environment variable `RENDER_EXTERNAL_URL` (e.g. `https://your-service.onrender.com`) and redeploy. If using the Blueprint (`render.yaml`), also set `RENDER_EXTERNAL_URL` in the service's Environment page.
7. Ensure only one running deployment uses this bot token; Telegram permits one webhook for a bot.

## Features
- 90-minute video duration limit
- Hindi, English, and Odia captions where available
- Original transcript or translation to Odia script
- TXT and SRT files

## Security
Never put your Telegram bot token in code or commit it to GitHub. Add it only as a Render environment variable.
