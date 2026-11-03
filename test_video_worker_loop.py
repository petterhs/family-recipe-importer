from __future__ import annotations

import unittest
from unittest.mock import patch

from video_worker import run_loop


class LoopTests(unittest.TestCase):
    def test_once_processes_one_job_and_stops(self):
        calls = []

        def process(*, base_url, token, worker_id, runner, **kwargs):
            calls.append((base_url, token, worker_id))
            return {"id": "job-1"}

        with patch("video_worker.process_one", side_effect=process):
            processed = run_loop("http://queue", "token", "no-kon-lx-016", once=True, poll_interval=0)

        self.assertEqual(processed, 1)
        self.assertEqual(calls, [("http://queue", "token", "no-kon-lx-016")])

    def test_loop_waits_when_queue_is_empty_then_processes_next_job(self):
        calls = []

        def process(*, base_url, token, worker_id, runner, **kwargs):
            calls.append(1)
            return None if len(calls) == 1 else {"id": "job-1"}

        with patch("video_worker.process_one", side_effect=process), patch("video_worker.time.sleep") as sleep:
            processed = run_loop("http://queue", "token", "worker", max_jobs=1, poll_interval=7)

        self.assertEqual(processed, 1)
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
