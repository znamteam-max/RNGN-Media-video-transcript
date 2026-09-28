# RNGN Media

Единый проект для работы с медиа: скачивание видео/фото с соцсетей, локальная транскрибация аудио/видео и получение существующих YouTube-субтитров.

Сейчас в репозитории два runtime, при этом основные пользовательские функции уже сведены в одну desktop-программу:

- **`desktop/` — RNGN Media Desktop**: единое Windows GUI для скачивания медиа, локальной транскрибации и получения существующих YouTube-субтитров;
- **`src/` — YouTube Transcript Telegram Bot**: существующий сервис, который достаёт manual/auto subtitles с YouTube без повторного распознавания речи.

## Desktop: объединённая версия

В одном Windows GUI уже объединены три функции:

1. **Media Downloader** — вставляешь одну ссылку, платформа определяется автоматически: YouTube / VK / TikTok / Instagram / X. Для обычных видео используется `yt-dlp`, для постов/каруселей доступен `gallery-dl`, видео после загрузки при необходимости приводится FFmpeg к MP4 H.264 + AAC для Premiere.
2. **Transcriber** — выбираешь локальный аудио- или видеофайл и получаешь TXT + SRT через `faster-whisper`. Поддержаны `large-v3` и `large-v3-turbo`, NVIDIA GPU при доступности и CPU fallback.
3. **YouTube Subtitles** — вставляешь YouTube URL, программа находит уже существующие manual/auto caption tracks, позволяет выбрать язык и сохраняет TXT + SRT без повторной транскрибации Whisper.

Рабочая база downloader зафиксирована как regression reference: manifest и контрольные SHA-256 лежат в `artifacts/downloader/`, а новый desktop-core повторяет её базовую маршрутизацию через `yt-dlp` / `gallery-dl` / FFmpeg. Оригинальные ZIP v5.16 и v5.16.1 остаются сохранены у владельца проекта и в рабочем архиве миграции; бинарные ZIP не добавлены в обычный Git history на первом этапе. Сложные platform-specific fallback'и переносим в общий код постепенно.

Подробности: [`desktop/README.md`](desktop/README.md) и [`desktop/ARCHITECTURE.md`](desktop/ARCHITECTURE.md).

### Запуск на Windows из исходников

Из папки `desktop`:

```bat
SETUP_WINDOWS.bat
RUN.bat
```

Первый скрипт создаёт `.venv`, ставит Python-зависимости и скачивает `yt-dlp`, `gallery-dl`, Deno и FFmpeg/ffprobe. Runtime binaries, cookies, модели Whisper и пользовательские медиа в Git не коммитятся.

Проверка core без скачивания моделей:

```bat
python test_core.py
```

## Windows installer

GitHub Actions собирает desktop-программу через PyInstaller и затем делает обычный Windows installer через Inno Setup. В installer включаются `yt-dlp`, `gallery-dl`, Deno и FFmpeg/ffprobe, поэтому пользователю не нужно отдельно ставить Python или media-tools. Workflow: `.github/workflows/desktop-build.yml`.

Исходный Telegram subtitle bot в `src/` сохраняется как отдельный runtime и regression/reference implementation.

## ZNAMBO Transcriber v1.7.0

Переданный архив v1.7.0 содержал Windows installer, а не оригинальные `.py`-исходники. Установщик был разобран для восстановления подтверждённого поведения приложения. `desktop/transcriber.py` — clean-room reimplementation этого core, а не заявление, что это оригинальный исходник.

Зафиксированная информация о восстановлении: [`docs/TRANSCRIBER_RECOVERY.md`](docs/TRANSCRIBER_RECOVERY.md).

---

# YouTube Video Transcript Telegram Bot

Telegram bot that accepts a YouTube link and returns a full transcript from the video's available subtitles.

If a video has several subtitle tracks, the bot asks which language to use and marks the source:

- `manual` / uploaded subtitles;
- `auto` / YouTube auto-generated subtitles.

The project has two bot runtimes:

- local long polling: `src/index.js`;
- Cloudflare Workers webhook: `src/worker.js`.

## Cloudflare Workers Deploy

The Worker is stateless. Language-choice buttons contain only `videoId` and track index; when a user taps a button, the Worker fetches the caption list again. No KV/D1 database is required.

1. Push this repository to GitHub.
2. In Cloudflare, create a Worker connected to this GitHub repository.
3. Use the repository `wrangler.toml`:

```toml
name = "youtube-video-transcript-bot"
main = "src/worker.js"
compatibility_date = "2026-05-07"
workers_dev = true
```

4. Add Worker secrets / environment variables:

```env
TELEGRAM_BOT_TOKEN=123456789:your_bot_token
WEBHOOK_SECRET=long_random_secret_for_telegram_header
SETUP_SECRET=long_random_secret_for_one_time_setup_url
YOUTUBE_TRANSCRIPT_DEV_API_KEY=your_api_key
```

Optional:

```env
YOUTUBE_PO_TOKEN=
```

`YOUTUBE_TRANSCRIPT_DEV_API_KEY` is strongly recommended for Cloudflare Workers. YouTube often returns HTTP 429 to direct requests from data center IPs, including Workers. When this key is present, the bot skips direct YouTube scraping and asks `https://www.youtubetranscript.dev/api/v2/transcribe` for the best available caption track.

5. Deploy the Worker.
6. Open this URL once in your browser:

```text
https://YOUR_WORKER.YOUR_SUBDOMAIN.workers.dev/setup-webhook?secret=SETUP_SECRET_VALUE
```

The Worker will call Telegram `setWebhook` for:

```text
https://YOUR_WORKER.YOUR_SUBDOMAIN.workers.dev/telegram/webhook
```

After that, send `/start` to the bot in Telegram and then send a YouTube link.

## Bot Local Run

Create `.env` from `.env.example`:

```env
TELEGRAM_BOT_TOKEN=123456789:your_bot_token
```

Run:

```bash
npm install
npm start
```

For Cloudflare local dev:

```bash
copy .dev.vars.example .dev.vars
npm run cf:dev
```

For direct Wrangler deploy:

```bash
npm run cf:deploy
```

## Bot checks

```bash
npm run check
```

Live YouTube smoke test:

```bash
npm run smoke:youtube -- M7lc1UVf-VE
```
