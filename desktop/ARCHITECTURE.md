# RNGN Media Desktop — Architecture

## Цель

Одна программа для Windows и macOS с четырьмя потоками работы:

```text
ссылка(и) ─────────► Скачать ─────────► видео / звук / фото  (+ «сразу расшифровать»)
ссылка ─────────────► Субтитры ────────► TXT / SRT / VTT без Whisper
аудио / видео файл ─► Расшифровка ─────► TXT / SRT / VTT (faster-whisper, GPU NVIDIA)
видео файл ─────────► Конвертер ───────► MP4 для Premiere / H.265 / ProRes / remux / звук
```

## Интерфейс

`main.py` открывает нативное окно через **pywebview** (Windows — Edge WebView2, macOS — WebKit)
и показывает `ui/index.html`. Вся логика интерфейса — `ui/app.js` (без сборщика и фреймворков),
стили — `ui/app.css` (токены светлой и тёмной темы; «как в системе» = без атрибута `data-theme`).

`ui/preview.html` + `ui/mock.js` — кликабельный макет без Python: те же методы, что у моста,
но с примерами данных. В установщик не входят.

JS вызывает Python через `window.pywebview.api.*` (класс `rngn.api.Api`). Python отправляет события
обратно через `window.rngn.receive({...})`: обновления заданий, перетащенные файлы, обновления.

## Пакет `rngn/`

| Модуль | Что делает |
|---|---|
| `api.py` | Мост для интерфейса: старт заданий, разбор ссылок, файлы, буфер обмена, настройки |
| `jobs.py` | Очередь: полоса `net` (скачивание, субтитры) и полоса `work` (расшифровка, конвертация) идут параллельно; отмена, повтор, журнал, история в `history.json` |
| `downloader.py` | Разбор ссылки (`yt-dlp --dump-single-json`), качество, плейлисты; скачивание видео/звука/отрезка; подготовка MP4 H.264+AAC для Premiere (NVENC при наличии) |
| `subtitles.py` | Дорожки субтитров YouTube (быстро через страницу) и любых сайтов через yt-dlp; TXT/SRT/VTT |
| `transcriber.py` | faster-whisper: модели `large-v3-turbo` / `large-v3`, микс языков, защита от зацикливания, кэш модели между заданиями |
| `gpu.py` | Поиск CUDA 12 + cuDNN 9 (своя папка или ZNAMBO Transcriber) и установка одной кнопкой |
| `converter.py` | Профили конвертации (перенесены из ZNAMBO Transcriber 1.7.0) |
| `tools.py` | Поиск yt-dlp / gallery-dl / FFmpeg / Deno, cookies, аргументы yt-dlp |
| `updater.py` | Самообновление yt-dlp (раз в сутки) и gallery-dl (раз в неделю) в папку пользователя, проверка новой версии программы |
| `procs.py` | Запуск процессов с отменой; при закрытии окна все дочерние процессы завершаются |
| `errors.py` | Перевод вывода инструментов в понятные сообщения с подсказкой |
| `settings.py` | Настройки в `settings.json` |
| `paths.py` | Папки программы и данных |

## Данные пользователя

`%LOCALAPPDATA%\RNGN-Media` (macOS: `~/Library/Application Support/RNGN Media`):

- `settings.json`, `history.json`;
- `models/` — модели Whisper (если их нет здесь, используются модели ZNAMBO Transcriber);
- `cuda-libs/` — библиотеки NVIDIA, скачанные кнопкой «Включить ускорение»;
- `tools/bin/` — обновлённые yt-dlp / gallery-dl (новее встроенных), `tools/versions.json`;
- `cookies.txt` — файл входа на сайты, если пользователь его загрузил;
- `webview/` — данные окна.

Результаты: папка из настроек (по умолчанию `Videos\RNGN Media`) с подпапками по сайтам,
`Transcripts`, `Subtitles`, `Converted`. Временные файлы — скрытая `.rngn-temp` там же (переезд = переименование).

## Сборка

- `rngn-media.spec` — одна спецификация PyInstaller для Windows и macOS.
- `bootstrap_tools.ps1` / `bootstrap_tools_macos.sh` — скачивают yt-dlp, gallery-dl, Deno, FFmpeg и PO Token provider.
- `rngn-media.iss` — установщик Inno Setup (версия передаётся из `rngn/__init__.py`).
- `.github/workflows/desktop-build.yml` — Windows, `desktop-macos.yml` — macOS, `desktop-check.yml` — тесты.
  Публикация релиза происходит только из `main`.

## Переменные для разработки

- `RNGN_TOOLS_DIR` — папка с готовыми yt-dlp/FFmpeg (например, из установленной программы);
- `RNGN_DATA_DIR` — отдельная папка данных для тестов;
- `RNGN_DEBUG=1` — инструменты разработчика в окне; `RNGN_DEBUG_PORT` — порт DevTools.

## Что не хранится в Git

Модели Whisper, библиотеки CUDA, cookies, скачанные медиа, venv, бинарники из `desktop/tools`.
