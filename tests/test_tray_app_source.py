import unittest
from pathlib import Path


class TrayAppSourceTests(unittest.TestCase):
    def test_quit_does_not_force_process_exit(self):
        source = Path("tray_app.py").read_text(encoding="utf-8")
        self.assertNotIn("os._exit(0)", source)


if __name__ == "__main__":
    unittest.main()
