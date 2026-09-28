from __future__ import annotations

import unittest

from platforms import detect_platform, platform_folder
from transcriber import Word, _build_cues, _format_txt, _timestamp


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


if __name__ == "__main__":
    unittest.main()
