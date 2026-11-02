from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from queue_api import create_app
from recipe_queue import Queue


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "queue.db"
        self.queue = Queue(self.db, lease_seconds=1)

    def tearDown(self):
        self.queue.close()
        self.tmp.cleanup()

    def test_claim_result_and_ownership(self):
        created = self.queue.create("https://youtu.be/example")
        claimed = self.queue.claim("fatman")
        self.assertEqual(claimed["id"], created["id"])
        with self.assertRaises(ValueError):
            self.queue.result(created["id"], "wrong-worker", {}, [])
        result = self.queue.result(created["id"], "fatman", {"name": "Soup"}, ["check servings"])
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["draft"]["name"], "Soup")

    def test_rejects_non_url(self):
        with self.assertRaises(ValueError):
            self.queue.create("file:///tmp/video.mp4")


class ApiTests(unittest.TestCase):
    def test_auth_and_create(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(str(Path(directory) / "queue.db"))
            app.config.update(TESTING=True)
            client = app.test_client()
            os.environ["QUEUE_TOKEN"] = "test-token"
            # app captures the token at creation, so recreate it
            app = create_app(str(Path(directory) / "queue2.db"))
            client = app.test_client()
            self.assertEqual(client.get("/health").status_code, 401)
            response = client.post("/jobs", headers={"Authorization": "Bearer test-token"}, json={"source_url": "https://example.com/reel"})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json["status"], "pending")
            os.environ.pop("QUEUE_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
