# RNGN Media Desktop

Единая Windows-программа для трёх задач, которые раньше жили отдельно.

## Что уже объединено

1. **Скачать медиа**
   - вставляешь одну ссылку;
   - платформа определяется автоматически: YouTube / VK / TikTok / Instagram / X;
   - основной downloader — `yt-dlp`;
   - для постов, каруселей и fallback-сценариев используется `gallery-dl`;
   - видео при необходимости приводится FFmpeg к MP4 H.264 + AAC для Premiere;
   - изображения сохраняются без перекодирования.

2. **Транскрибировать**
   - локальный аудио- или видеофайл → TXT и SRT;
   - `faster-whisper`;
   - профили `large-v3` и `large-v3-turbo`;
   - NVIDIA GPU при доступности;
   - автоматический fallback на CPU при CUDA-проблемах;
   - модели хранятся вне Git и скачиваются один раз.

3. **YouTube субтитры**
   - вставляешь YouTube URL;
   - программа находит уже существующие manual/auto caption tracks;
   - показывает язык и источник дорожки;
   - сохраняет выбранную дорожку как SRT + обычный TXT;
   - Whisper в этом режиме не запускается.

## Готовый Windows installer

GitHub Actions собирает программу через PyInstaller и упаковывает её через Inno Setup.

Installer включает:
- Python runtime приложения;
- `yt-dlp`;
- `gallery-dl`;
- Deno;
- FFmpeg + ffprobe;
- зависимости transcriber.

То есть для установки готовой сборки отдельно ставить Python и media-tools не нужно.

Workflow: `.github/workflows/desktop-build.yml`.

Release: `desktop-v0.2.0`.

## Запуск из исходников

Из папки `desktop`:

```bat
SETUP_WINDOWS.bat
RUN.bat
```

`SETUP_WINDOWS.bat` создаёт `.venv`, ставит Python-зависимости и скачивает media-tools в `desktop/tools/bin`.

По умолчанию результаты сохраняются в `Videos/RNGN Media`:

- `YouTube/`, `VK/`, `TikTok/`, `Instagram/`, `X_Twitter/` — скачанные медиа;
- `Transcripts/` — результаты локальной транскрибации;
- `YouTube_Subtitles/` — готовые YouTube TXT/SRT.

## Проверки

Без скачивания Whisper-моделей:

```bat
python test_core.py
```

GitHub Actions дополнительно проверяет синтаксис, core unit tests, PyInstaller build, наличие всех runtime tools и сборку Windows installer.

## Legacy / regression reference

Рабочая ветка Media Downloader v5.16/5.16.1 не используется как новая GUI-архитектура, но её поведение остаётся regression reference. Контрольные данные сохранены в `../artifacts/downloader/`.

Переданный ZNAMBO Transcriber v1.7.0 был Windows installer без оригинальных Python-исходников. `transcriber.py` — восстановленный clean-room core на подтверждённом стеке `faster-whisper`, а не заявление, что это исходный source v1.7.0.

Подробности: `../docs/TRANSCRIBER_RECOVERY.md`.
