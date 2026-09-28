# RNGN Media Video Transcript / Media Studio

Этот репозиторий становится единым домом для работы с медиа.

## Windows: RNGN Media Studio

Новая desktop-ветка объединяет две рабочие задачи в одной программе:
- скачивание видео с YouTube / VK / TikTok / Instagram / X по одной ссылке, без ручного выбора платформы;
- локальную транскрибацию аудио и видео, SRT и конвертацию для Premiere на базе ZNAMBO Transcriber 1.7.0.

Исходники Windows-программы лежат в desktop/.
GitHub Actions собирает RNGN-Media-Studio-Setup.exe и portable ZIP.

## YouTube subtitles

Первоначальная функция репозитория сохранена: код Telegram/Cloudflare-бота в src/ вытаскивает существующие YouTube-субтитры, различает manual/auto tracks и умеет выбирать язык.

Следующий этап — встроить это в RNGN Media Studio как третий режим: YouTube URL → получить оригинальные/автоматические субтитры → TXT/SRT без Whisper, когда они уже есть у YouTube.

## Структура

- desktop/ — единая Windows-программа Download + Transcribe + SRT + Video Converter;
- src/ — существующий YouTube transcript bot;
- test/ — тесты YouTube transcript bot;
- docs/UNIFIED_MEDIA_STUDIO.md — план дальнейшего объединения.
