"""docs_merge.py - appends the sections of docs_update_*.md to status.md, backlog.md, AUTOMATION_TEST_PLAN.md and QUALITY_CRITERIA.md (2026-11-06).
APPEND-ONLY: the existing text is never changed or removed. A section whose first heading is already in the target is skipped (safe to run twice).
A backup copy NAME.bak_docs_merge is written before the first change. Usage (repo folder):  python3 docs_merge.py        (dry run: python3 docs_merge.py --dry)
"""
import glob
import re
import shutil
import sys

TARGETS = ["status.md", "backlog.md", "AUTOMATION_TEST_PLAN.md", "QUALITY_CRITERIA.md"]
dry = "--dry" in sys.argv
text = {t: open(t, encoding="utf-8").read() for t in TARGETS}
orig = dict(text)
for src in sorted(glob.glob("docs_update_*.md")):
    parts = re.split(r"^## >>> APPEND TO (\S+)\s*$", open(src, encoding="utf-8").read(), flags=re.M)
    for i in range(1, len(parts), 2):
        name, body = parts[i], parts[i + 1].strip("\n")
        if name not in text:
            print("SKIP unknown target", name, "in", src)
            continue
        head = next((l for l in body.splitlines() if l.startswith("## ")), body.splitlines()[0])
        if head in text[name]:
            print("already there:", name, "|", head[:80])
            continue
        text[name] = text[name].rstrip("\n") + "\n\n" + body + "\n"
        print("ADD", name, "|", head[:80], "<-", src)
for t in TARGETS:
    assert text[t].startswith(orig[t].rstrip("\n")), "existing text changed in " + t + " - stopped"
    if text[t] != orig[t] and not dry:
        shutil.copyfile(t, t + ".bak_docs_merge")
        open(t, "w", encoding="utf-8").write(text[t])
    print(t, len(orig[t].splitlines()), "->", len(text[t].splitlines()), "lines", "(dry run)" if dry else "")
