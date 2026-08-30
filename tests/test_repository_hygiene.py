from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from scripts.check_repository_hygiene import find_violations


ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_current_repository_is_clean(self) -> None:
        self.assertEqual(find_violations(ROOT), [])

    def test_retired_interfaces_are_detected_but_protected_files_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "python").mkdir()
            (root / "python" / "old.py").write_text(
                "field = '" + "bandwidth" + "_mhz'\n"
                + "route = '" + "/api/" + "v1/status'\n",
                encoding="utf-8",
            )
            (root / "reports").mkdir()
            (root / "reports" / ("stage" + "12.md")).write_text(
                "fs_" + "adc and /api/" + "v1 are historical evidence\n",
                encoding="utf-8",
            )
            (root / "for_me.md").write_text("Stage " + "7\n", encoding="utf-8")

            violations = find_violations(root)

        self.assertEqual(len(violations), 2)
        self.assertTrue(all(item.startswith("python/old.py:1") or item.startswith("python/old.py:2") for item in violations))

    def test_latest_only_layout_and_stage_archive(self) -> None:
        for retired in (
            ROOT / "config" / "stage33",
            ROOT / "deploy" / "stage33",
            ROOT / "reports" / "maintenance",
            ROOT / "reports" / "board",
            ROOT / "reports" / "vivado",
        ):
            self.assertFalse(retired.exists(), retired)

        for root_name in ("config", "deploy", "scripts"):
            for path in (ROOT / root_name).rglob("*"):
                if path.is_file():
                    self.assertNotIn("stage33", path.relative_to(ROOT).as_posix().lower())

        active_reports = {
            path.name
            for path in (ROOT / "reports" / "stages").glob("*.md")
            if path.name != "README.md"
        }
        self.assertTrue(active_reports)
        self.assertTrue(
            all(re.match(r"(?:32|33|34|35)", name) for name in active_reports),
            active_reports,
        )
        archived_reports = list((ROOT / "reports" / "stages" / "arch").glob("*.md"))
        self.assertTrue(archived_reports)
        self.assertTrue(
            all(not re.match(r"(?:32|33)", path.name) for path in archived_reports)
        )

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("build/vivado/latest", readme)
        self.assertIn("[T510 仓库宪法](AGENTS.md)", readme)
        constitution = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("10s -> 20s -> 30s -> 60s", constitution)
        self.assertIn("单次最长 `600s`", constitution)

    def test_closed_stage_cannot_return_to_active_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "scripts").mkdir()
            (root / "scripts" / ("t510_stage" + "34" + "f_probe.py")).write_text(
                "NAME = 'stage" + "34" + "f-d2'\n", encoding="utf-8"
            )
            (root / "reports").mkdir()
            (root / "reports" / "34f_closure.md").write_text(
                "Stage " + "34f is historical.\n", encoding="utf-8"
            )

            violations = find_violations(root)

        self.assertTrue(
            any("closed Stage " + "34f path" in item for item in violations), violations
        )
        self.assertTrue(
            any("closed Stage " + "34f identifier" in item for item in violations),
            violations,
        )
        self.assertTrue(all(not item.startswith("reports/") for item in violations))


if __name__ == "__main__":
    unittest.main()
