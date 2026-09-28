# RNGN Media Desktop — Architecture

## Цель

Один Windows GUI и один GitHub-репозиторий для трёх медиа-потоков:

```text
URL ───────────────► Download ─────────► media file
local media file ─► Transcribe ────────► TXT / SRT
YouTube URL ───────► Existing captions ► TXT / SRT
```

Пользователь не выбирает платформу для скачивания вручную.

## Modules

### `app.py`

Tkinter GUI. Сейчас три вкладки:

- **Скачать медиа**
- **Транскрибировать**
- **YouTube субтитры**

Тяжёлые операции выполняются в worker threads. GUI получает status/progress/log через очередь, чтобы окно не зависало во время сетевых операций и транскрибации.

### `platforms.py`

Определение платформы по URL и единые имена output folders.

### `downloader.py`

Маршрутизация загрузки:

- YouTube / VK / TikTok — сначала `yt-dlp`;
- Instagram / X — сначала `gallery-dl`, затем fallback;
- для поддерживаемых platform failures используется обратный fallback;
- FFmpeg/ffprobe проверяют кодеки;
- если файл не Premiere-ready, он перекодируется в MP4 H.264 + AAC.

Runtime tools ищутся:
1. рядом с packaged EXE в `tools/bin`;
2. в dev tree;
3. в legacy/local Media Downloader install как fallback.

### `transcriber.py`

Локальная транскрибация через `faster-whisper`.

- `large-v3` — точный профиль;
- `large-v3-turbo` — быстрый профиль;
- CUDA используется при наличии;
- при CUDA/DLL/driver ошибке выполняется fallback на CPU;
- TXT и SRT формируются локально;
- Whisper models хранятся в `%LOCALAPPDATA%\\RNGN-Media\\models`.

### `youtube_subtitles.py`

Получение уже существующих YouTube captions без Whisper.

- `yt-dlp --dump-single-json` получает список `subtitles` и `automatic_captions`;
- manual и auto tracks не смешиваются;
- выбранная дорожка скачивается как VTT/SRT;
- FFmpeg используется как fallback-конвертер VTT → SRT;
- из SRT строится обычный TXT с дедупликацией rolling auto-captions.

### `bootstrap_tools.ps1`

Скачивает:
- yt-dlp;
- gallery-dl Windows build;
- Deno;
- FFmpeg + ffprobe.

### Packaging

`desktop-build.yml`:
1. ставит Python dependencies;
2. скачивает media-tools;
3. собирает `RNGN Media.exe` через PyInstaller;
4. добавляет tools рядом с EXE;
5. собирает `RNGN-Media-Setup-0.2.0.exe` через Inno Setup;
6. загружает Actions artifact;
7. публикует GitHub release `desktop-v0.2.0`.

## Что не удалено

Корневой `src/` — существующий YouTube Transcript Telegram Bot. Он остаётся отдельным runtime и reference implementation; desktop-модуль не требует его запуска.

## Что не хранится в Git

- Whisper models;
- cookies;
- media downloads;
- Python venv;
- runtime binaries из `desktop/tools/bin` — они скачиваются build/setup процессом;
- пользовательские локальные файлы.
