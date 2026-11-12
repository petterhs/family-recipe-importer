from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_worker import _ocr, _ocr_quality, _vtt_text, extract


class WorkerTests(unittest.TestCase):
    def test_vtt_is_deduplicated(self):
        vtt = "WEBVTT\n\n00:00.000 --> 00:01.000\nMix flour\n\n00:01.000 --> 00:02.000\nMix flour\n\n00:02.000 --> 00:03.000\nAdd eggs <i>now</i>"
        self.assertEqual(_vtt_text(vtt), "Mix flour Add eggs now")

    def test_extract_metadata_and_subtitles(self):
        def fake_runner(command, **kwargs):
            directory = command[command.index("--output") + 1].replace("source.%(ext)s", "source.en.vtt")
            with open(directory, "w", encoding="utf-8") as output:
                output.write("WEBVTT\n\n00:00 --> 00:01\nAdd two eggs\n")
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "title": "Eggs", "uploader": "Chef", "duration": 12,
                "webpage_url": "https://example.test/video", "thumbnail": "https://example.test/image.jpg",
                "description": "A simple recipe",
            }), "")

        result = extract("https://example.test/video", fake_runner, transcribe=False, ocr=False)
        self.assertEqual(result["title"], "Eggs")
        self.assertEqual(result["captions"][0]["text"], "Add two eggs")
        self.assertEqual(result["transcription"], None)
        self.assertEqual(result["ocr"], [])
        self.assertEqual(result["warnings"], [])

    def test_ocr_samples_frames_and_uses_sparse_text_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            def fake_runner(command, **kwargs):
                if command[0] == "yt-dlp":
                    Path(directory, "video.mp4").touch()
                elif command[0] == "ffmpeg":
                    frames = Path(directory, "frames")
                    frames.mkdir(exist_ok=True)
                    Path(frames, "frame-0001.png").touch()
                elif command[0] == "tesseract":
                    self.assertIn("--psm", command)
                    self.assertIn("11", command)
                    return subprocess.CompletedProcess(command, 0, "One Pot Creamy Tomato Chicken Pasta", "")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("video_worker.shutil.which", return_value="/bin/tool"):
                result = _ocr("https://example.test/video", directory, fake_runner)

        self.assertEqual(result[0]["text"], "One Pot Creamy Tomato Chicken Pasta")

    def test_ocr_quality_rejects_single_word_noise(self):
        self.assertEqual(_ocr_quality([{"frame": "1.png", "text": "garlic"}]), "unusable")
        self.assertEqual(_ocr_quality([{"frame": "1.png", "text": "smoked paprika"}]), "usable")

    def test_description_referencing_comments_is_explicitly_limited(self):
        def fake_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "title": "Chicken", "description": "Instructions are in the pinned comment."
            }), "")

        result = extract("https://example.test/video", fake_runner, transcribe=False, ocr=False)
        self.assertTrue(any("comment" in warning.lower() for warning in result["warnings"]))

    def test_missing_optional_tools_are_reported_as_warnings(self):
        def fake_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, json.dumps({"title": "Soup"}), "")

        result = extract("https://example.test/video", fake_runner)
        self.assertEqual(result["stage"], "metadata-captions-transcription-ocr")
        self.assertTrue(any("transcription" in warning.lower() for warning in result["warnings"]))
        self.assertTrue(any("ocr" in warning.lower() for warning in result["warnings"]))

    def test_extract_failure_is_clear(self):
        def fake_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "private video")

        with self.assertRaisesRegex(RuntimeError, "private video"):
            extract("https://example.test/video", fake_runner, transcribe=False, ocr=False)


if __name__ == "__main__":
    unittest.main()
