#!/usr/bin/env python3
"""Check repository-local Markdown links without accessing the network."""
from __future__ import annotations
import re
from pathlib import Path
from urllib.parse import unquote
ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^]]*\]\((<[^>]+>|[^)]+)\)")
SKIP = {".git", "build", "target", "demo-ant.cache", "demo-ant.gen", "demo-ant.hw", "demo-ant.ip_user_files", "demo-ant.runs", "demo-ant.sim"}
def violations(root: Path = ROOT) -> list[str]:
    failures=[]
    for markdown in sorted(root.rglob("*.md")):
        relative=markdown.relative_to(root)
        if any(part in SKIP for part in relative.parts): continue
        for line_number,line in enumerate(markdown.read_text(encoding="utf-8").splitlines(),1):
            for match in LINK.finditer(line):
                raw=match.group(1).strip("<>").split(maxsplit=1)[0]
                if raw.startswith(("http://","https://","mailto:","#")): continue
                target_text=unquote(raw.split("#",1)[0])
                if not target_text: continue
                target=(root/target_text.lstrip("/")) if raw.startswith("/") else (markdown.parent/target_text)
                if not target.exists(): failures.append(f"{relative}:{line_number}: missing {raw}")
    return failures
def main() -> int:
    failures=violations()
    if failures:
        print("T510_MARKDOWN_LINKS_FAIL"); print("\n".join(failures)); return 1
    print("T510_MARKDOWN_LINKS_PASS"); return 0
if __name__ == "__main__": raise SystemExit(main())
