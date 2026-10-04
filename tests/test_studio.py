import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


class StudioCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.dict(os.environ, {"YDTS_DATA_DIR": str(self.tmp / "데이터 データ")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_settings_persist_and_recover(self):
        from studio import settings as cfg
        values = cfg.load()
        self.assertEqual(values["product_mode"], "natural")
        values.update(quality="best", models_dir="D:/모델")
        cfg.save(values)
        self.assertEqual(cfg.load()["quality"], "best")
        cfg.settings_file().write_text("{broken", encoding="utf-8")
        self.assertEqual(cfg.load()["quality"], "balanced")
        self.assertTrue(list(cfg.data_dir().glob("studio_settings.corrupt-*.json")))

    def test_queue_persists_and_running_returns_to_pending(self):
        from studio.jobs import RUNNING, PENDING, JobQueue
        queue = JobQueue()
        job = queue.add({"prompt": "a"})
        job.state = RUNNING
        queue.save()
        again = JobQueue()
        self.assertEqual(again.jobs[0].state, PENDING)
        queue.path.write_text("not json", encoding="utf-8")
        broken = JobQueue()
        self.assertEqual(broken.jobs, [])
        self.assertIn("손상", broken.recovered_note)

    def _backend_outcome(self, status, **kw):
        from studio.backend import JobOutcome
        return JobOutcome(status, **kw)

    def test_runner_pause_waiting_failed_and_close(self):
        from studio.jobs import CANCELLED, DONE, FAILED, PENDING, JobQueue, Runner
        queue = JobQueue()
        for n in range(4):
            queue.add({"n": n})
        calls = []

        def execute(job):
            calls.append(job.payload["n"])
            if job.payload["n"] == 1:
                return self._backend_outcome("waiting", reasons=["GPU 여유 2000 MiB"])
            if job.payload["n"] == 2:
                return self._backend_outcome("failed", error={"code": "BACKEND_CRASH", "message": "x", "action": "retry"})
            return self._backend_outcome("done", result={"candidates": [{}], "job_dir": "j"})

        runner = Runner(queue, execute, recheck_seconds=0.01)
        self.assertEqual(runner.run_next(), "ran")            # job 0 done
        self.assertEqual(runner.run_next(), "waiting")        # job 1 stays pending with a reason
        self.assertEqual(queue.jobs[1].state, PENDING)
        self.assertIn("GPU", queue.jobs[1].waiting_reason)
        runner.pause_after_current()
        self.assertEqual(runner.run_next(), "paused")
        queue.set_paused(False)
        queue.jobs[1].payload["n"] = 9                         # resources free now
        self.assertEqual(runner.run_next(), "ran")
        self.assertEqual(runner.run_next(), "ran")             # job 2 fails, queue continues
        self.assertEqual(queue.jobs[2].state, FAILED)
        self.assertTrue(queue.retry(queue.jobs[2].id))
        runner.closing = True                                  # app closing mid-job -> pending again
        runner.execute = lambda job: self._backend_outcome("cancelled")
        self.assertEqual(runner.run_next(), "closing")
        self.assertEqual(queue.jobs[2].state, PENDING)

    def test_backend_maps_exit_codes(self):
        from studio import backend as be
        exe = self.tmp / "fake.cmd"
        result = {"status": "done", "candidates": [{"files": {"full": "a.png"}}], "job_dir": "j"}

        class FakeProc:
            def __init__(self, code, data, path):
                self.code, self.data, self.path = code, data, path
                self.stdout = iter(['{"progress": 0.5, "message": "생성 중"}\n'])
                self.pid = 1

            def wait(self):
                if self.data is not None:
                    Path(self.path).write_text(json.dumps(self.data), encoding="utf-8")
                return self.code

            def poll(self):
                return self.code

        exe.write_text("x")
        backend = be.Backend(str(exe))
        seen = []
        for code, data, expected in ((0, result, "done"), (3, {"status": "waiting", "reasons": ["RAM"]}, "waiting"),
                                     (2, {"status": "failed", "error": {"code": "MODELS_MISSING", "message": "m",
                                                                        "action": "a"}}, "failed"),
                                     (1, None, "failed"), (0, {"status": "done", "candidates": []}, "failed")):
            with mock.patch.object(be.subprocess, "Popen", lambda args, **kw: FakeProc(code, data, args[args.index("--result") + 1])):
                outcome = backend.run_job({"x": 1}, self.tmp / f"w{code}", seen.append)
            self.assertEqual(outcome.status, expected, (code, data))
        self.assertEqual(seen[0]["message"], "생성 중")

    def test_shop_project_layouts(self):
        import cv2
        from editor.project import generate_shop_project
        image = np.full((700, 1800, 3), 40, np.uint8)
        path = self.tmp / "배너.png"
        cv2.imencode(".png", image)[1].tofile(str(path))
        state = generate_shop_project(str(path), (1800, 700), {"title": "Sale", "subtitle": "Today", "cta": "Shop"},
                                      text_region=(0.05, 0.18, 0.40, 0.64), cta_region=(0.05, 0.72, 0.20, 0.13),
                                      subject_boxes=[[0.55, 0.2, 0.3, 0.7]])
        self.assertEqual(set(state.documents), {"A", "B", "C"})
        for document in state.documents.values():
            self.assertEqual((document.canvas_width, document.canvas_height), (1800, 700))
            roles = {layer.role for layer in document.ordered()}
            self.assertTrue({"main_title", "subtitle", "cta"} <= roles)
            self.assertFalse({"episode_badge", "channel_label"} & roles)
        self.assertEqual(state.documents["A"].by_role("cta").fill, "#FFFFFF")   # dark background -> light pill
        title_b = state.documents["B"].by_role("main_title")
        self.assertGreater(title_b.y, 700 * 0.6)              # mirrored side holds the product -> bottom band


if __name__ == "__main__":
    unittest.main()
