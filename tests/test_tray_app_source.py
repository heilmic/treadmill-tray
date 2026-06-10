import re
import unittest
from pathlib import Path


class TrayAppSourceTests(unittest.TestCase):
    def test_quit_does_not_force_process_exit(self):
        source = Path("tray_app.py").read_text(encoding="utf-8")
        self.assertNotIn("os._exit(0)", source)

    def test_fallback_schritt_konstante_realistisch(self):
        """Stellt sicher, dass _SCHRITT_LAENGE_M nicht auf den alten Wert 0.75
        zurückfällt und nah am kalibrierten Wert 0.51 liegt."""
        source = Path("tray_app.py").read_text(encoding="utf-8")

        # Konstante muss im Quelltext definiert sein
        match = re.search(r"_SCHRITT_LAENGE_M\s*=\s*([0-9.]+)", source)
        self.assertIsNotNone(match, "_SCHRITT_LAENGE_M nicht in tray_app.py gefunden")

        wert = float(match.group(1))
        # Alter Fehler-Wert war 0.75 – der neue Wert muss darunter liegen
        self.assertLess(wert, 0.75, "_SCHRITT_LAENGE_M muss kleiner als 0,75 sein")
        # Sanity-Check: realistischer Bereich 0,40–0,65 m/Schritt
        self.assertGreaterEqual(wert, 0.40, "_SCHRITT_LAENGE_M unter realistischem Minimum 0,40")
        self.assertLessEqual(wert, 0.65, "_SCHRITT_LAENGE_M über realistischem Maximum 0,65")

        # Schätzung für die bekannte Kalibrierungssituation:
        # 50 Schritte * 0,51 m/Schritt = 25,5 m -> Rückrechnung ergibt ~50 Schritte
        dist_m = 50 * 0.51
        geschaetzte_schritte = int(dist_m / wert)
        self.assertGreaterEqual(geschaetzte_schritte, 45)
        self.assertLessEqual(geschaetzte_schritte, 55)

    def test_fallback_schrittlogik_wird_auch_fuer_historie_verwendet(self):
        source = Path("tray_app.py").read_text(encoding="utf-8")
        self.assertIn("def _steps_for_data(self, data: TreadmillData) -> int:", source)
        self.assertIn("total_steps = self._steps_for_data(data)", source)
        self.assertIn("self._hist_start_steps = self._steps_for_data(data)", source)


if __name__ == "__main__":
    unittest.main()
