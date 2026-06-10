import importlib
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import patch


class HistoryStepRegressionTests(unittest.TestCase):
    @staticmethod
    def _install_import_stubs():
        pystray = types.ModuleType("pystray")
        pystray.Icon = object
        pystray.MenuItem = lambda *args, **kwargs: (args, kwargs)
        pystray.Menu = lambda *args, **kwargs: (args, kwargs)
        sys.modules["pystray"] = pystray

        pil = types.ModuleType("PIL")
        image_mod = types.ModuleType("PIL.Image")
        image_mod.Image = object
        image_mod.new = lambda *args, **kwargs: object()
        draw_mod = types.ModuleType("PIL.ImageDraw")

        class _FakeDraw:
            def ellipse(self, *args, **kwargs):
                pass

            def rounded_rectangle(self, *args, **kwargs):
                pass

            def line(self, *args, **kwargs):
                pass

        draw_mod.Draw = lambda *args, **kwargs: _FakeDraw()
        pil.Image = image_mod
        pil.ImageDraw = draw_mod
        sys.modules["PIL"] = pil
        sys.modules["PIL.Image"] = image_mod
        sys.modules["PIL.ImageDraw"] = draw_mod

        bleak = types.ModuleType("bleak")
        bleak.BleakScanner = object
        sys.modules["bleak"] = bleak

        bluetooth_manager_fba = types.ModuleType("bluetooth_manager_fba")
        bluetooth_manager_fba.BluetoothManagerFBA = object
        sys.modules["bluetooth_manager_fba"] = bluetooth_manager_fba

    def test_history_uses_distance_fallback_even_when_live_session_baseline_was_cleared(self):
        self._install_import_stubs()
        sys.modules.pop("tray_app", None)
        tray_app = importlib.import_module("tray_app")

        app = tray_app.TreadmillTrayApp.__new__(tray_app.TreadmillTrayApp)
        app._session_start_time = datetime(2026, 1, 1, 12, 0, 0)
        app._session_start_dist = None
        app._hist_start_dist = 1000
        app._hist_start_steps = 0
        app._hist_start_calories = 0
        app._session_target_speed = 4.5
        app.current_speed = 4500

        data = types.SimpleNamespace(
            distance=1128,
            steps=0,
            real_electricity_steps=None,
            calories=12,
            duration_seconds=180,
            unit_mode=0,
        )

        captured = {}

        def fake_save_entry(entry):
            captured.update(entry)

        with patch.object(tray_app, "save_entry", fake_save_entry):
            tray_app.TreadmillTrayApp._save_session(app, data)

        self.assertEqual(captured["steps"], tray_app._estimated_steps_from_distance(128))
        self.assertGreater(captured["steps"], 0)


if __name__ == "__main__":
    unittest.main()
