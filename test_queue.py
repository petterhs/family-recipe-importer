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
        claimed = self.queue.claim("test-worker")
        self.assertEqual(claimed["id"], created["id"])
        with self.assertRaises(ValueError):
            self.queue.result(created["id"], "wrong-worker", {}, [])
        result = self.queue.result(created["id"], "test-worker", {"name": "Soup"}, ["check servings"])
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["draft"]["name"], "Soup")

    def test_duplicate_active_source_returns_existing_job(self):
        first, created = self.queue.create_or_get("https://www.youtube.com/shorts/example")
        self.assertTrue(created)
        second, created = self.queue.create_or_get("https://www.youtube.com/shorts/example")
        self.assertFalse(created)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["status"], "pending")

    def test_failed_source_can_be_retried(self):
        first, _ = self.queue.create_or_get("https://example.com/retry")
        self.queue.claim("worker")
        self.queue.fail(first["id"], "worker", "temporary failure")
        second, created = self.queue.create_or_get("https://example.com/retry")
        self.assertTrue(created)
        self.assertNotEqual(second["id"], first["id"])

    def test_approval_and_import_transitions(self):
        created = self.queue.create("https://example.com/approve")
        claimed = self.queue.claim("worker")
        assert claimed is not None
        self.queue.result(claimed["id"], "worker", {"title": "Soup"}, [])
        approved = self.queue.approve(created["id"])
        self.assertEqual(approved["status"], "approved")
        imported = self.queue.mark_imported(created["id"], "https://mealie.example/recipe/soup")
        self.assertEqual(imported["status"], "imported")
        self.assertEqual(imported["payload"]["mealie_url"], "https://mealie.example/recipe/soup")

    def test_approval_requires_review_and_import_requires_approval(self):
        created = self.queue.create("https://example.com/not-ready")
        with self.assertRaises(ValueError):
            self.queue.approve(created["id"])
        with self.assertRaises(ValueError):
            self.queue.mark_imported(created["id"], "https://mealie.example/recipe/nope")

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
            self.assertEqual(response.json["job"]["status"], "pending")
            duplicate = client.post("/jobs", headers={"Authorization": "Bearer test-token"}, json={"source_url": "https://example.com/reel"})
            self.assertEqual(duplicate.status_code, 200)
            self.assertTrue(duplicate.json["duplicate"])
            self.assertEqual(duplicate.json["job"]["id"], response.json["job"]["id"])
            os.environ.pop("QUEUE_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
