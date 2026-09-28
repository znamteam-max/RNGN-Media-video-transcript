# RNGN Media Studio — Windows

Первая объединённая desktop-сборка проекта.

Что уже объединено:
- локальная транскрибация аудио/видео через faster-whisper;
- TXT-транскрипт;
- точные SRT;
- конвертер видео для Premiere;
- загрузка по одной ссылке с автоопределением YouTube / VK / TikTok / Instagram / X;
- автоматический анализ доступных разрешений;
- MP4 H.264 + AAC для Premiere;
- оригинальный звук в WAV;
- отмена зависшей загрузки.

Платформу вручную выбирать не нужно.

GitHub Actions во время Windows-сборки добавляет yt-dlp, Deno, gallery-dl и FFmpeg/ffprobe, поэтому они входят в итоговый installer.

Если сайт требует авторизацию, положи Netscape cookies-файл сюда:
%LOCALAPPDATA%\RNGN Media Studio\cookies.txt

Код ZNAMBO Transcriber 1.7.0 перенесён как рабочий стек без переписывания Whisper/SRT/GPU-логики.

Существующий YouTube transcript bot в корне репозитория сохранён — он станет следующим модулем desktop-программы.
