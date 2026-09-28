# ZNAMBO Transcriber v1.7.0 — recovery note

Исходный архив, переданный для объединения, содержал только `ZNAMBO-Transcriber-Setup.exe` (Inno Setup 6.7.0), без исходников.

Для сохранения рабочей логики установщик был разобран и проанализирован. Внутри найден PyInstaller/Python 3.11 desktop app со следующими собственными модулями:

- `desktop_app.py`
- `desktop_v7.py`, `desktop_v8.py`, `desktop_v9.py`, `desktop_v11.py`, entrypoint `desktop_v12.py`
- `transcribe.py`
- `subtitle_audio_engine.py`
- `video_converter.py`

Подтверждённая логика v1.7.0:

- `faster-whisper` + `CTranslate2`;
- модели `large-v3` (beam 5) и `large-v3-turbo` (beam 3);
- CUDA/float16 при доступной NVIDIA, CPU/int8 fallback;
- `vad_filter=True`, `min_silence_duration_ms=700`;
- word-level timing для SRT;
- отдельные TXT/SRT/VTT/JSON routines в core;
- video conversion через FFmpeg, включая H.264 Premiere, HEVC, ProRes, remux;
- локальные модели в `%LOCALAPPDATA%`.

`desktop/transcriber.py` — чистая повторная реализация core-функции v1.7.0 для нового общего приложения. Это не выдаётся за оригинальный исходник: оригинальный `.py` отсутствовал в переданном архиве.

При дальнейшей миграции нужно сохранять этот документ и не удалять installer artifact у владельца проекта, пока новая версия не пройдёт regression test на тех же медиа.

## Исходный artifact

- Файл: `ZNAMBO-Transcriber-v1.7.0-SRT-Video-Converter (1).zip`
- Размер: около 84 MB
- SHA-256: `f52014e895c1a89558f126db9d7d0746caf79aebd5b279b1fd82e50b980f428a`

Сам 84 MB installer archive не добавлен в обычный Git history на этом этапе. Хэш фиксирует точный artifact, от которого сделано восстановление.
