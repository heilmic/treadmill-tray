import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


class WorkoutHistoryTests(unittest.TestCase):
    def _reload_module(self):
        sys.modules.pop("workout_history", None)
        return importlib.import_module("workout_history")

    def test_uses_appdata_env_for_history_location(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_appdata = os.environ.get("APPDATA")
            try:
                os.environ["APPDATA"] = tmpdir
                mod = self._reload_module()
                expected = Path(tmpdir) / "treadmill-tray" / "workout_history.json"
                self.assertEqual(mod._history_file(), expected)
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata

    def test_save_entry_persists_json_under_appdata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_appdata = os.environ.get("APPDATA")
            try:
                os.environ["APPDATA"] = tmpdir
                mod = self._reload_module()
                entry = mod.make_entry(datetime(2026, 1, 2, 3, 4, 5), 60, 1.234, 1000, 55, 4.5, 5.0)
                mod.save_entry(entry)
                saved = mod._history_file()
                self.assertTrue(saved.exists())
                self.assertEqual(mod.load_history()[0]["distance_km"], 1.234)
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata


if __name__ == "__main__":
    unittest.main()
