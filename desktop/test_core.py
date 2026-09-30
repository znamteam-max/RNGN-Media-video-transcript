from __future__ import annotations

import unittest

from app import clean_pasted_url, is_paste_shortcut
from downloader import _format_selector, quality_choices_from_info

from platforms import detect_platform, platform_folder
from transcriber import Word, _build_cues, _format_txt, _timestamp
from youtube_subtitles import _extract_video_id, _json3_to_srt, _vtt_to_srt, _xml_to_srt, srt_to_text, tracks_from_info


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

    def test_original_track_is_first(self) -> None:
        info = {
            "automatic_captions": {
                "ru": [{"ext": "vtt", "name": "Russian"}],
                "ru-orig": [{"ext": "vtt", "name": "Russian"}],
                "en": [{"ext": "vtt", "name": "English"}],
            }
        }
        tracks = tracks_from_info(info)
        self.assertEqual(tracks[0].language_code, "ru-orig")
        self.assertTrue(tracks[0].is_original)
        self.assertIn("оригинал", tracks[0].label)

    def test_extract_video_id(self) -> None:
        self.assertEqual(
            _extract_video_id("https://www.youtube.com/watch?v=I67BkHZffnk"),
            "I67BkHZffnk",
        )
        self.assertEqual(_extract_video_id("https://youtu.be/I67BkHZffnk"), "I67BkHZffnk")

    def test_json3_to_srt(self) -> None:
        srt = _json3_to_srt(
            {
                "events": [
                    {
                        "tStartMs": 1000,
                        "dDurationMs": 1500,
                        "segs": [{"utf8": "Hello "}, {"utf8": "world"}],
                    }
                ]
            }
        )
        self.assertIn("00:00:01,000 --> 00:00:02,500", srt)
        self.assertIn("Hello world", srt)

    def test_vtt_to_srt(self) -> None:
        vtt = """WEBVTT

00:00:01.000 --> 00:00:02.500
Hello <b>world</b>
"""
        srt = _vtt_to_srt(vtt)
        self.assertIn("00:00:01,000 --> 00:00:02,500", srt)
        self.assertIn("Hello world", srt)

    def test_xml_to_srt(self) -> None:
        xml = '<transcript><text start="1.0" dur="1.5">Hello &amp; world</text></transcript>'
        srt = _xml_to_srt(xml)
        self.assertIn("00:00:01,000 --> 00:00:02,500", srt)
        self.assertIn("Hello & world", srt)

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


class DownloaderQualityTests(unittest.TestCase):
    def test_quality_selector_uses_exact_height(self) -> None:
        selector = _format_selector("1080p — MP4 H.264 + AAC")
        self.assertIn("height=1080", selector)
        self.assertNotIn("height<=1080", selector)

    def test_unverified_quality_uses_ceiling(self) -> None:
        selector = _format_selector("1080p — без анализа → MP4 H.264 + AAC")
        self.assertIn("height<=1080", selector)

    def test_only_real_heights_are_offered(self) -> None:
        info = {
            "formats": [
                {"height": 1080, "vcodec": "avc1.640028", "acodec": "none", "tbr": 5000},
                {"height": 720, "vcodec": "vp09.00.31.08", "acodec": "none", "tbr": 2500},
                {"height": 360, "vcodec": "avc1.42001E", "acodec": "none", "tbr": 800},
                {"height": None, "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128},
            ]
        }
        choices = quality_choices_from_info(info)
        heights = [choice.height for choice in choices]
        self.assertEqual(heights, [1080, 720, 360])
        self.assertNotIn(2160, heights)
        self.assertEqual(choices[0].label, "1080p — MP4 H.264 + AAC")
        self.assertIn("VP9", choices[1].label)
        self.assertIn("→ MP4 H.264 + AAC", choices[1].label)


class UiHelpersTests(unittest.TestCase):
    def test_cyrillic_ctrl_v_keycode(self) -> None:
        self.assertTrue(is_paste_shortcut(86, "Cyrillic_em"))
        self.assertTrue(is_paste_shortcut(86, "v"))

    def test_clean_pasted_url(self) -> None:
        self.assertEqual(
            clean_pasted_url("  https://www.youtube.com/watch?v=abc&t=10s\n"),
            "https://www.youtube.com/watch?v=abc&t=10s",
        )
        self.assertEqual(
            clean_pasted_url("[video](https://x.com/name/status/123)"),
            "https://x.com/name/status/123",
        )


if __name__ == "__main__":
    unittest.main()
