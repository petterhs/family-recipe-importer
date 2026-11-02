from __future__ import annotations

import json
import subprocess
import unittest

from video_worker import _vtt_text, extract


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

        result = extract("https://example.test/video", fake_runner)
        self.assertEqual(result["title"], "Eggs")
        self.assertEqual(result["captions"][0]["text"], "Add two eggs")
        self.assertEqual(result["warnings"], [])

    def test_extract_failure_is_clear(self):
        def fake_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "private video")

        with self.assertRaisesRegex(RuntimeError, "private video"):
            extract("https://example.test/video", fake_runner)


if __name__ == "__main__":
    unittest.main()
