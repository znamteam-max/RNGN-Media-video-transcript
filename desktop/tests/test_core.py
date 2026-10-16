from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from rngn import errors, settings as settings_module
from rngn.downloader import (
    QualityChoice,
    YtdlpProgress,
    default_height,
    format_selector,
    human_speed,
    media_info_from_json,
    parse_timecode,
    quality_choices_from_info,
    validate_clip_range,
)
from rngn.platforms import clean_pasted_url, detect_platform, extract_urls, platform_folder, platform_label
from rngn.procs import CancelToken, OperationCancelled, Report
from rngn.subtitles import (
    extract_video_id,
    json3_to_srt,
    srt_to_text,
    srt_to_vtt,
    tracks_from_info,
    vtt_to_srt,
    xml_to_srt,
)
from rngn.tools import Access, Toolset, cookie_domains, looks_like_cookies_file, pot_provider_args, version_key
from rngn.transcriber import (
    LANGUAGES,
    MIXED_LANGUAGE_SENTINEL,
    LoopFilter,
    Word,
    build_cues,
    format_srt,
    format_txt,
    format_vtt,
    language_code,
    language_label,
    looks_like_internal_loop,
    srt_time,
    wrap_cue,
)


class PlatformDetectionTests(unittest.TestCase):
    def test_known_platforms(self) -> None:
        cases = {
            "https://www.youtube.com/watch?v=abc": "YouTube",
            "https://youtu.be/abcdefghijk": "YouTube",
            "https://vk.com/video1_2": "VK",
            "https://vkvideo.ru/video-1_2": "VK",
            "https://www.tiktok.com/@name/video/1": "TikTok",
            "https://www.instagram.com/reel/test/": "Instagram",
            "https://x.com/example/status/1": "X_Twitter",
            "https://twitter.com/example/status/1": "X_Twitter",
            "https://rutube.ru/video/abc/": "Rutube",
            "https://dzen.ru/video/watch/abc": "Dzen",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(detect_platform(url), expected)

    def test_unknown_goes_to_other_but_has_readable_label(self) -> None:
        self.assertEqual(detect_platform("https://example.com/video"), "Other")
        self.assertEqual(platform_folder("SomethingElse"), "Other")
        self.assertEqual(platform_label("Other", "https://www.example.com/v"), "example.com")

    def test_lookalike_host_is_not_matched(self) -> None:
        self.assertEqual(detect_platform("https://notyoutube.com/watch?v=1"), "Other")

    def test_clean_pasted_url(self) -> None:
        self.assertEqual(
            clean_pasted_url("  https://www.youtube.com/watch?v=abc&t=10s\n"),
            "https://www.youtube.com/watch?v=abc&t=10s",
        )
        self.assertEqual(clean_pasted_url("[video](https://x.com/name/status/123)"), "https://x.com/name/status/123")

    def test_extract_several_urls(self) -> None:
        text = "первая https://youtu.be/aaaaaaaaaaa\nвторая https://vk.com/video1_2, и снова https://youtu.be/aaaaaaaaaaa"
        self.assertEqual(extract_urls(text), ["https://youtu.be/aaaaaaaaaaa", "https://vk.com/video1_2"])


class TranscriptFormattingTests(unittest.TestCase):
    def test_srt_timestamp(self) -> None:
        self.assertEqual(srt_time(65.432), "00:01:05,432")

    def test_cues_split_on_pause(self) -> None:
        words = [Word(0.0, 0.4, "Привет"), Word(0.45, 0.9, "мир."), Word(2.0, 2.4, "Новая"), Word(2.45, 2.9, "фраза.")]
        cues = build_cues(words)
        self.assertEqual([cue[2] for cue in cues], ["Привет мир.", "Новая фраза."])

    def test_plain_text_paragraphs(self) -> None:
        text = format_txt([(0.0, "Первая фраза."), (2.0, "Вторая фраза.")], False)
        self.assertIn("Первая фраза.", text)
        self.assertIn("Вторая фраза.", text)

    def test_timestamps_in_txt(self) -> None:
        self.assertIn("[00:01:05] Привет", format_txt([(65.0, "Привет")], True))

    def test_long_cue_wraps_into_two_balanced_lines(self) -> None:
        wrapped = wrap_cue("Это довольно длинная реплика, которая не помещается в одну строку субтитров")
        lines = wrapped.split("\n")
        self.assertEqual(len(lines), 2)
        self.assertLess(abs(len(lines[0]) - len(lines[1])), 15)

    def test_srt_and_vtt_output(self) -> None:
        cues = [(1.0, 2.5, "Hello world")]
        self.assertIn("00:00:01,000 --> 00:00:02,500", format_srt(cues))
        vtt = format_vtt(cues)
        self.assertTrue(vtt.startswith("WEBVTT"))
        self.assertIn("00:00:01.000 --> 00:00:02.500", vtt)

    def test_languages(self) -> None:
        self.assertEqual(LANGUAGES["Авто · микс языков"], MIXED_LANGUAGE_SENTINEL)
        expected = {"ru", "en", "fr", "es", "zh", "de", "pt", "it", "ja", "ko", "ar"}
        configured = {code for code in LANGUAGES.values() if code and code != MIXED_LANGUAGE_SENTINEL}
        self.assertTrue(expected.issubset(configured))
        self.assertEqual(language_code("ru"), "ru")
        self.assertIsNone(language_code("auto"))
        self.assertEqual(language_label("zh"), "中文")
        self.assertEqual(language_label("xx"), "xx")


class LoopProtectionTests(unittest.TestCase):
    def test_hallucination_loop_is_detected(self) -> None:
        self.assertTrue(looks_like_internal_loop("спасибо за просмотр " * 12))

    def test_normal_speech_is_kept(self) -> None:
        text = (
            "Сегодня мы поговорим о том, как устроен матч, почему команда проиграла в третьем периоде "
            "и что тренер сказал после игры журналистам на пресс-конференции в раздевалке"
        )
        self.assertFalse(looks_like_internal_loop(text))

    def test_more_than_two_identical_segments_are_dropped(self) -> None:
        loop = LoopFilter()
        kept = [loop.keep("Да.") for _ in range(4)]
        self.assertEqual(kept, [True, True, False, False])
        self.assertTrue(loop.keep("Нет."))
        self.assertEqual(loop.dropped, 2)


class SubtitleTests(unittest.TestCase):
    def test_manual_and_auto_tracks_are_separate(self) -> None:
        info = {
            "subtitles": {"ru": [{"ext": "vtt", "name": "Russian"}], "live_chat": [{"ext": "json"}]},
            "automatic_captions": {"en": [{"ext": "vtt", "name": "English"}], "ru": [{"ext": "vtt", "name": "Russian"}]},
        }
        labels = [track.label for track in tracks_from_info(info)]
        self.assertEqual(labels[0], "Русский (ru) — вручную")
        self.assertIn("Русский (ru) — авто", labels)
        self.assertIn("English (en) — авто", labels)
        self.assertFalse(any("live_chat" in label for label in labels))

    def test_original_track_is_first_and_translations_are_hidden(self) -> None:
        info = {
            "automatic_captions": {
                "ru": [{"ext": "vtt"}],
                "ru-orig": [{"ext": "vtt"}],
                "en": [{"ext": "vtt"}],
                "de": [{"ext": "vtt"}],
            }
        }
        tracks = tracks_from_info(info)
        self.assertEqual([track.language_code for track in tracks], ["ru-orig"])
        self.assertIn("оригинал", tracks[0].label)

    def test_auto_tracks_follow_video_language_without_orig(self) -> None:
        info = {"language": "en", "automatic_captions": {"en": [{"ext": "vtt"}], "fr": [{"ext": "vtt"}]}}
        self.assertEqual([t.language_code for t in tracks_from_info(info)], ["en"])

    def test_extract_video_id(self) -> None:
        self.assertEqual(extract_video_id("https://www.youtube.com/watch?v=I67BkHZffnk"), "I67BkHZffnk")
        self.assertEqual(extract_video_id("https://youtu.be/I67BkHZffnk"), "I67BkHZffnk")
        self.assertEqual(extract_video_id("https://www.youtube.com/shorts/I67BkHZffnk"), "I67BkHZffnk")

    def test_converters(self) -> None:
        srt = json3_to_srt({"events": [{"tStartMs": 1000, "dDurationMs": 1500, "segs": [{"utf8": "Hello "}, {"utf8": "world"}]}]})
        self.assertIn("00:00:01,000 --> 00:00:02,500", srt)
        self.assertIn("Hello world", srt)
        self.assertIn("Hello world", vtt_to_srt("WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nHello <b>world</b>\n"))
        self.assertIn("Hello & world", xml_to_srt('<transcript><text start="1.0" dur="1.5">Hello &amp; world</text></transcript>'))
        vtt = srt_to_vtt(srt)
        self.assertTrue(vtt.startswith("WEBVTT"))
        self.assertIn("00:00:01.000 --> 00:00:02.500", vtt)

    def test_srt_to_text_dedupes_rolling_captions(self) -> None:
        srt = (
            "1\n00:00:00,000 --> 00:00:01,000\nПривет\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nПривет мир\n\n"
            "3\n00:00:02,000 --> 00:00:03,000\nПривет мир\n\n"
            "4\n00:00:03,000 --> 00:00:04,000\nНовая фраза.\n"
        )
        text = srt_to_text(srt)
        self.assertEqual(text.count("Привет мир"), 1)
        self.assertNotIn("Привет Привет", text)
        self.assertIn("Новая фраза.", text)


class QualityTests(unittest.TestCase):
    INFO = {
        "title": "Матч",
        "duration": 125,
        "formats": [
            {"height": 1080, "vcodec": "avc1.640028", "acodec": "none", "tbr": 5000, "filesize": 50_000_000},
            {"height": 720, "vcodec": "vp09.00.31.08", "acodec": "none", "tbr": 2500},
            {"height": 360, "vcodec": "avc1.42001E", "acodec": "none", "tbr": 800},
            {"height": None, "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128, "filesize": 2_000_000},
        ],
    }

    def test_only_real_heights_are_offered(self) -> None:
        choices = quality_choices_from_info(self.INFO)
        self.assertEqual([choice.height for choice in choices], [1080, 720, 360])
        self.assertTrue(choices[0].direct)
        self.assertIn("без перекодирования", choices[0].note)
        self.assertFalse(choices[1].direct)
        self.assertIn("VP9", choices[1].note)
        self.assertEqual(choices[0].size, 52_000_000)

    def test_vk_unknown_audio_is_not_called_silent(self) -> None:
        info = {"formats": [{"format_id": "hls", "height": None, "vcodec": "unknown", "acodec": "unknown"}]}
        choice = quality_choices_from_info(info)[0]
        self.assertIn("звук: не определён источником", choice.note)
        self.assertNotIn("без звука", choice.note)

    def test_default_height_prefers_1080_then_lower(self) -> None:
        def make(*heights):
            return [QualityChoice(h, f"{h}p", "", False) for h in heights]

        self.assertEqual(default_height(make(2160, 1080, 720)), 1080)
        self.assertEqual(default_height(make(2160, 720, 480)), 720)
        self.assertEqual(default_height(make(2160, 1440)), 1440)
        self.assertIsNone(default_height(make(None)))

    def test_selector_exact_height_has_safe_fallbacks(self) -> None:
        selector = format_selector(1080, exact=True)
        self.assertTrue(selector.startswith("bv*[height=1080][vcodec^=avc1]"))
        self.assertIn("height<=1080", selector)
        self.assertTrue(selector.endswith("/b"))

    def test_selector_ceiling_without_analysis(self) -> None:
        self.assertTrue(format_selector(720, exact=False).startswith("bv*[height<=720]"))

    def test_media_info_from_json(self) -> None:
        info = media_info_from_json("https://www.youtube.com/watch?v=abcdefghijk", self.INFO, Access("mweb"))
        data = info.to_dict()
        self.assertEqual(data["site"], "YouTube")
        self.assertEqual(data["default_height"], 1080)
        self.assertEqual(data["access"]["client"], "mweb")

    def test_playlist_entries(self) -> None:
        info = {"_type": "playlist", "title": "Лучшие голы", "entries": [{"id": "abcdefghijk", "title": "Гол 1"}]}
        result = media_info_from_json("https://www.youtube.com/playlist?list=PL1", info, None)
        self.assertEqual(result.kind, "playlist")
        self.assertEqual(result.entries[0]["url"], "https://www.youtube.com/watch?v=abcdefghijk")

    def test_timecodes(self) -> None:
        self.assertEqual(parse_timecode("75"), 75)
        self.assertEqual(parse_timecode("01:15"), 75)
        self.assertEqual(parse_timecode("1:02:03"), 3723)
        self.assertEqual(validate_clip_range("01:00", "01:30"), (60, 90))
        with self.assertRaises(ValueError):
            validate_clip_range("01:30", "01:00")
        with self.assertRaises(ValueError):
            validate_clip_range("10:00", "11:00", duration=300)


class ProgressTests(unittest.TestCase):
    def _tracker(self):
        values: list[float | None] = []
        statuses: list[str] = []
        report = Report(statuses.append, values.append, lambda _s: None)
        return YtdlpProgress(report, 85.0, "Скачиваю видео"), values, statuses

    def test_video_and_audio_parts_never_go_backwards(self) -> None:
        tracker, values, statuses = self._tracker()
        tracker.on_line("[info] abc: Downloading 1 format(s): 137+140")
        for pct in ("10.0%", "50.0%", "100.0%"):
            tracker.on_line(f"RNGNPROG|{pct}|5.00MiB/s|00:10|137")
        for pct in ("0.0%", "50.0%", "100.0%"):
            tracker.on_line(f"RNGNPROG|{pct}|1.00MiB/s|00:01|140")
        numbers = [value for value in values if value is not None]
        self.assertEqual(numbers, sorted(numbers))
        self.assertAlmostEqual(numbers[-1], 85.0)
        self.assertTrue(any("МБ/с" in status for status in statuses))

    def test_unknown_percent_is_indeterminate(self) -> None:
        tracker, values, _ = self._tracker()
        tracker.on_line("RNGNPROG|Unknown %|N/A|N/A|NA")
        self.assertEqual(values, [None])

    def test_human_speed(self) -> None:
        self.assertEqual(human_speed("  5.23MiB/s"), "5.23 МБ/с")
        self.assertEqual(human_speed("Unknown B/s"), "")


class ErrorTests(unittest.TestCase):
    def test_classification(self) -> None:
        self.assertEqual(errors.classify("ERROR: Sign in to confirm you're not a bot"), "auth")
        self.assertEqual(errors.classify("HTTP Error 429: Too Many Requests"), "rate_limit")
        self.assertEqual(errors.classify("ERROR: Video unavailable"), "unavailable")
        self.assertEqual(errors.classify("OSError: [Errno 28] No space left on device"), "disk")
        self.assertEqual(errors.classify("something odd"), "unknown")

    def test_friendly_text_mentions_site(self) -> None:
        message, hint = errors.friendly("auth", "YouTube")
        self.assertIn("YouTube", message)
        self.assertTrue(hint)


class CancelTests(unittest.TestCase):
    def test_cancel_token(self) -> None:
        token = CancelToken()
        token.raise_if_cancelled()
        token.cancel()
        with self.assertRaises(OperationCancelled):
            token.raise_if_cancelled()

    def test_cancel_stops_running_process(self) -> None:
        import sys

        from rngn.procs import run_streaming

        token = CancelToken()
        threading.Timer(0.5, token.cancel).start()
        started = time.monotonic()
        with self.assertRaises(OperationCancelled):
            run_streaming([sys.executable, "-c", "import time\nwhile True: time.sleep(0.1)"],
                          on_line=lambda _l: None, token=token)
        self.assertLess(time.monotonic() - started, 8)


class ToolsTests(unittest.TestCase):
    def _toolset(self, root: Path, with_provider: bool) -> Toolset:
        bin_dir = root / "tools" / "bin"
        bin_dir.mkdir(parents=True)
        for name in ("yt-dlp.exe", "gallery-dl.exe", "ffmpeg.exe", "ffprobe.exe", "deno.exe"):
            (bin_dir / name).write_bytes(b"test")
        if with_provider:
            (root / "tools" / "yt-dlp-plugins").mkdir(parents=True)
            (root / "tools" / "yt-dlp-plugins" / "bgutil-ytdlp-pot-provider.zip").write_bytes(b"zip")
            (root / "tools" / "bgutil-ytdlp-pot-provider" / "server").mkdir(parents=True)
        return Toolset(bin_dir / "yt-dlp.exe", bin_dir / "gallery-dl.exe", bin_dir / "ffmpeg.exe",
                       bin_dir / "ffprobe.exe", bin_dir / "deno.exe", root / "tools")

    def test_pot_provider_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = pot_provider_args(self._toolset(Path(tmp), True))
            self.assertIn("--plugin-dirs", args)
            self.assertTrue(any("server_home=" in item for item in args))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(pot_provider_args(self._toolset(Path(tmp), False)), [])

    def test_version_compare(self) -> None:
        self.assertGreater(version_key("2026.09.01"), version_key("2026.08.19"))
        self.assertGreater(version_key("2026.08.19.1"), version_key("2026.08.19"))

    def test_cookie_file_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.txt"
            path.write_text(
                "# Netscape HTTP Cookie File\n"
                ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tx\n"
                "#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\ty\n",
                encoding="utf-8",
            )
            self.assertTrue(looks_like_cookies_file(path))
            self.assertEqual(cookie_domains(path), ["instagram.com", "youtube.com"])


class SettingsTests(unittest.TestCase):
    def test_roundtrip_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "settings.json"
            store = settings_module.Settings(file)
            store.update({"theme": "dark", "transcribe": {"model": "large"}, "unknown": 1})
            store.update({"theme": "purple"})
            again = settings_module.Settings(file)
            self.assertEqual(again.get("theme"), "dark")
            self.assertEqual(again.get("transcribe", "model"), "large")
            self.assertEqual(again.get("transcribe", "language"), "mixed")
            self.assertNotIn("unknown", json.loads(file.read_text(encoding="utf-8")))


class JobQueueTests(unittest.TestCase):
    def test_download_and_transcription_run_in_parallel_and_cancel(self) -> None:
        from rngn import jobs as jobs_module

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(jobs_module.paths, "data_dir", return_value=Path(tmp)):
            started: dict[str, float] = {}

            def fake_execute(self, job, report):
                started[job.kind] = time.monotonic()
                while not job.token.wait(0.05):
                    pass
                raise OperationCancelled()

            with mock.patch.object(jobs_module.JobManager, "_execute", fake_execute):
                events: list[dict] = []
                manager = jobs_module.JobManager(settings_module.Settings(Path(tmp) / "s.json"), events.append)
                first = manager.submit("download", "видео", {"url": "https://youtu.be/x"})
                second = manager.submit("transcribe", "файл", {"file": "x.mp3"})
                deadline = time.monotonic() + 5
                while len(started) < 2 and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(set(started), {"download", "transcribe"})
                self.assertTrue(manager.cancel(first.id))
                self.assertTrue(manager.cancel(second.id))
                deadline = time.monotonic() + 5
                while manager.active_count() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(manager.jobs[first.id].state, "cancelled")
                manager.shutdown()
                history = json.loads((Path(tmp) / "history.json").read_text(encoding="utf-8"))
                self.assertEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
