import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from editor.selftest import run_editor_self_test

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class ProEditorGuiTests(unittest.TestCase):
    def run_project(self, name):
        try:
            from app import App
            app = App()
        except tk.TclError as exc:
            self.skipTest(f"Tk desktop is unavailable: {exc}")
        try:
            with tempfile.TemporaryDirectory() as raw:
                outcome = run_editor_self_test(app, EXAMPLES / name, workdir=raw)
        finally:
            app.destroy()
        failed = {key: value for key, value in outcome["results"].items() if value != "PASS"}
        self.assertEqual({}, failed, outcome["details"].get("traceback", outcome["details"]))
        timings = outcome["details"]["timings"]
        # Perceived latency (edit -> frame on screen); target <= 120 ms, generous CI ceiling here.
        self.assertLess(timings["property"]["median_ms"], 250)
        self.assertLess(timings["drag"]["median_ms"], 150)
        return outcome

    def test_tokyo_chill_project_end_to_end(self):
        self.run_project("tokyo_chill_project")

    def test_old_pop_project_end_to_end(self):
        self.run_project("old_pop_lounge_project")


if __name__ == "__main__":
    unittest.main()
