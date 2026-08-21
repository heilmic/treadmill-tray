import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import workout_history as wh


class WorkoutHistoryTests(unittest.TestCase):
    def test_history_file_lives_next_to_app(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(wh, "app_dir", return_value=Path(tmpdir)):
                expected = Path(tmpdir) / "workout_history.json"
                self.assertEqual(wh._history_file(), expected)

    def test_save_entry_persists_json_next_to_app(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(wh, "app_dir", return_value=Path(tmpdir)):
                entry = wh.make_entry(datetime(2026, 1, 2, 3, 4, 5), 60, 1.234, 1000, 55, 4.5, 5.0)
                wh.save_entry(entry)
                saved = wh._history_file()
                self.assertTrue(saved.exists())
                self.assertEqual(wh.load_history()[0]["distance_km"], 1.234)


if __name__ == "__main__":
    unittest.main()
