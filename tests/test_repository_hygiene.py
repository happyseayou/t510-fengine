from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
