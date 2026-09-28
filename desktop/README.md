# RNGN Media Desktop

Первая объединённая desktop-версия двух рабочих инструментов:

1. **Media Downloader** — одна ссылка, автоматическое определение YouTube / VK / TikTok / Instagram / X; видео приводится к MP4 H.264 + AAC для Premiere, фото сохраняются как есть.
2. **Transcriber** — локальный аудио- или видеофайл → TXT и SRT через `faster-whisper`; `large-v3` или `large-v3-turbo`, GPU при доступности с fallback на CPU.

Существующий YouTube subtitle bot в корне репозитория не удалён и не переписан. Следующий этап — перенести его функцию «вставил YouTube URL → получил уже существующие manual/auto subtitles» в третий tab desktop-программы.

## Windows

```text
SETUP_WINDOWS.bat
RUN.bat
```

`SETUP_WINDOWS.bat` создаёт `.venv`, устанавливает Python-зависимости и скачивает `yt-dlp`, `gallery-dl`, `FFmpeg/ffprobe` и `Deno` в `desktop/tools/bin`.

По умолчанию результаты сохраняются в `Videos/RNGN Media`:

- `YouTube/`, `VK/`, `TikTok/`, `Instagram/`, `X_Twitter/` — скачанные медиа;
- `Transcripts/` — `.transcript.txt` и `.subtitles.srt`.

## Почему downloader не переписан вслепую

Контрольные SHA-256 рабочей v5.16/v5.16.1 сохранены в `../artifacts/downloader/README.md`. Новый Python frontend использует те же базовые инструменты (`yt-dlp`, `gallery-dl`, FFmpeg) и автоматическую платформенную маршрутизацию. Оригинальные ZIP/legacy snapshot остаются сохранены вне обычного Git history до отдельного archival шага; их используем как regression reference для сложных fallback-случаев (Instagram cookies, X video+audio, TikTok CDN, YouTube clients).
