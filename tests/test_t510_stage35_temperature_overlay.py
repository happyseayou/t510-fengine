from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts/stage-35/t510_stage35_simple_explorer.py"
JAVASCRIPT = ROOT / "scripts/stage-35/web/explorer/app.js"
QUEUE = ROOT / "scripts/stage-35/t510_stage35_temperature_overlay_queue.py"


class Stage35TemperatureOverlayTests(unittest.TestCase):
    def test_server_exposes_sealed_temperature(self) -> None:
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn("T510_STAGE35_TIME_TEMPERATURE_V1", source)
        self.assertIn('"temperature": self.time_temperature', source)
        self.assertIn("timestamps are outside the formal window", source)

    def test_power_plot_uses_temperature_right_axis(self) -> None:
        source = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('name: "PL 温度"', source)
        self.assertIn('yaxis: "y2"', source)
        self.assertIn('text: "PL 温度 (°C)"', source)
        self.assertIn("未插值或外推", source)

    def test_update_is_current_only_and_preserves_stage36(self) -> None:
        source = QUEUE.read_text(encoding="utf-8")
        self.assertIn("expected at least 880 in-window PL temperature points", source)
        self.assertIn('staged = install / ".current.next"', source)
        self.assertNotIn("previous", source)
        self.assertIn('request_json("http://127.0.0.1:8036/healthz")', source)


if __name__ == "__main__":
    unittest.main()
