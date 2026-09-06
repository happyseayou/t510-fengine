from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts/stage-36/t510_stage36_explorer.py"
QUEUE = ROOT / "scripts/stage-36/t510_stage36_explorer_queue.py"
WEB = ROOT / "scripts/stage-36/web/explorer"


class Stage36ExplorerTests(unittest.TestCase):
    def test_server_is_stage36_and_read_only(self) -> None:
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn('DATA_ROOT = Path("/var/lib/t510").resolve()', source)
        self.assertIn("T510_STAGE36_SIMPLE_EXPLORER_CONFIG_V1", source)
        self.assertIn("T510_STAGE36_SIMPLE_EXPLORER_META_V1", source)
        self.assertIn("Stage 36：TIME_ONLY", source)
        self.assertIn("def do_POST", source)
        self.assertIn("self.send_bytes(405", source)

    def test_queue_reuses_stage35_math_and_preserves_8035(self) -> None:
        source = QUEUE.read_text(encoding="utf-8")
        self.assertIn("t510_stage35_explorer_prepare", source)
        self.assertIn("t510_stage35_simple_prepare", source)
        self.assertIn("t510_stage35_time_long_prepare.py", source)
        self.assertIn('request_json("http://127.0.0.1:8035/healthz")', source)
        self.assertIn('--bind 0.0.0.0:8036', source)
        self.assertIn("TIME_GAIN = 1.9998779296875", source)
        self.assertIn("SPEC_GAIN = 3.999755859375", source)
        self.assertIn("trim_spec_record(spec_record)", source)
        self.assertIn("resume_after_spec_coverage_failure", source)

    def test_static_page_uses_local_fixed_assets_and_comparison(self) -> None:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        js = (WEB / "stage36-app.js").read_text(encoding="utf-8")
        self.assertIn("Stage 36：", html)
        self.assertIn('id="stageComparison"', html)
        self.assertIn('/static/plotly-strict.min.js', html)
        self.assertIn('/static/stage36-app.js', html)
        self.assertIn("META.stage35_comparison", js)
        self.assertIn("数值放大本身不代表科学性能改善", js)


if __name__ == "__main__":
    unittest.main()
