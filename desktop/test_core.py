from __future__ import annotations

import unittest

from app import clean_pasted_url

from platforms import detect_platform, platform_folder
from transcriber import Word, _build_cues, _format_txt, _timestamp
from youtube_subtitles import srt_to_text, tracks_from_info


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
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(detect_platform(url), expected)

    def test_unknown_goes_to_other(self) -> None:
        self.assertEqual(detect_platform("https://example.com/video"), "Other")
        self.assertEqual(platform_folder("SomethingElse"), "Other")


class TranscriptFormattingTests(unittest.TestCase):
    def test_srt_timestamp(self) -> None:
        self.assertEqual(_timestamp(65.432), "00:01:05,432")

    def test_cues_split_on_pause(self) -> None:
        words = [
            Word(0.0, 0.4, "Привет"),
            Word(0.45, 0.9, "мир."),
            Word(2.0, 2.4, "Новая"),
            Word(2.45, 2.9, "фраза."),
        ]
        cues = _build_cues(words)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0][2], "Привет мир.")
        self.assertEqual(cues[1][2], "Новая фраза.")

    def test_plain_text_paragraphs(self) -> None:
        text = _format_txt([(0.0, "Первая фраза."), (2.0, "Вторая фраза.")], False)
        self.assertIn("Первая фраза.", text)
        self.assertIn("Вторая фраза.", text)


class YoutubeSubtitleTests(unittest.TestCase):
    def test_manual_and_auto_tracks_are_separate(self) -> None:
        info = {
            "subtitles": {
                "ru": [{"ext": "vtt", "name": "Russian"}],
                "live_chat": [{"ext": "json"}],
            },
            "automatic_captions": {
                "en": [{"ext": "vtt", "name": "English"}],
                "ru": [{"ext": "vtt", "name": "Russian"}],
            },
        }
        tracks = tracks_from_info(info)
        labels = [track.label for track in tracks]
        self.assertEqual(labels[0], "Русский (ru) — вручную")
        self.assertIn("Русский (ru) — авто", labels)
        self.assertIn("English (en) — авто", labels)
        self.assertFalse(any("live_chat" in label for label in labels))

    def test_srt_to_text_dedupes_rolling_captions(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:01,000
Привет

2
00:00:01,000 --> 00:00:02,000
Привет мир

3
00:00:02,000 --> 00:00:03,000
Привет мир

4
00:00:03,000 --> 00:00:04,000
Новая фраза.
"""
        text = srt_to_text(srt)
        self.assertEqual(text.count("Привет мир"), 1)
        self.assertNotIn("Привет Привет", text)
        self.assertIn("Новая фраза.", text)


if __name__ == "__main__":
    unittest.main()


class UiHelpersTests(unittest.TestCase):
    def test_clean_pasted_url(self) -> None:
        self.assertEqual(
            clean_pasted_url("  https://www.youtube.com/watch?v=abc&t=10s\n"),
            "https://www.youtube.com/watch?v=abc&t=10s",
        )
        self.assertEqual(
            clean_pasted_url("[video](https://x.com/name/status/123)"),
            "https://x.com/name/status/123",
        )
