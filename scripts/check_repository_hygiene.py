#!/usr/bin/env python3
"""Fail when retired interfaces or stage history leak into active sources."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


SKIP_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".vmcp",
    ".Xil",
    "__pycache__",
    "build",
    "demo-ant.cache",
    "demo-ant.gen",
    "demo-ant.hw",
    "demo-ant.ip_user_files",
    "demo-ant.runs",
    "demo-ant.sim",
    "overlay",
    "reports",
    "target",
}
SKIP_DIR_PREFIXES = (".xsim",)
SKIP_FILES = {"for_me.md", "gridstack-all.js", "echarts-all.js"}
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".html",
    ".ipynb",
    ".js",
    ".json",
    ".md",
    ".py",
    ".rs",
    ".service",
    ".sh",
    ".sv",
    ".svh",
    ".tcl",
    ".toml",
    ".txt",
    ".v",
    ".xdc",
    ".xpr",
}
TEXT_FILENAMES = {".gitignore", "Cargo.lock", "Cargo.toml", "Makefile"}


def _retired_stage_pattern(*, path: bool) -> re.Pattern[str]:
    separator = r"[ _-]?" if path else r"[ _]?"
    return re.compile(
        rf"(?i)\bstage{separator}(?:3[0-2]|[12][0-9]|[0-9])(?![0-9])"
    )


CONTENT_RULES = (
    ("retired stage identifier", _retired_stage_pattern(path=False)),
    ("retired sample-rate field", re.compile("bandwidth" + "_mhz")),
    ("retired RFDC-rate field", re.compile(r"\b" + "fs_" + r"adc\b")),
    ("retired REST route", re.compile("/api/" + "v1")),
    ("retired receiver option", re.compile("--spec-" + "layout")),
)


def _skip_relative_path(relative: Path) -> bool:
    if relative.name in SKIP_FILES:
        return True
    for part in relative.parts[:-1]:
        if part in SKIP_DIR_NAMES or part.startswith(SKIP_DIR_PREFIXES):
            return True
    return False


def _text_candidate(path: Path) -> bool:
    return path.name in TEXT_FILENAMES or path.suffix.lower() in TEXT_SUFFIXES


def find_violations(root: Path) -> list[str]:
    root = root.resolve()
    path_rule = _retired_stage_pattern(path=True)
    violations: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _skip_relative_path(relative):
            continue
        relative_text = relative.as_posix()
        if path_rule.search(relative_text):
            violations.append(f"{relative_text}: retired stage path")
        if not _text_candidate(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(lines, start=1):
            for label, rule in CONTENT_RULES:
                if rule.search(line):
                    violations.append(f"{relative_text}:{line_number}: {label}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: parent of scripts/)",
    )
    args = parser.parse_args()
    violations = find_violations(args.root)
    if violations:
        print("T510_REPOSITORY_HYGIENE_FAIL")
        for violation in violations:
            print(violation)
        return 1
    print("T510_REPOSITORY_HYGIENE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
