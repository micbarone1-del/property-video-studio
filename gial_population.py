"""gial_population.py - the GIAL population for the Luma volume tests (2026-11-04, Michele: "prendi tutta la popolazione GIAL e identifica quelli che passano").

Two read-only steps, no Claude, no spend, no job touched:
  python3 gial_population.py list OUT.txt [--exclude 1336,1189,...]   reads the agency page of GIAL on relinx.it, then every listing page (1 s apart), keeps the
        APARTMENTS (appartamento / attico, sale or rent), writes 'canonical-url | id slug' lines, the format of relinx_pilot_check.py
  python3 gial_population.py report LOG [LOG...]                       reads relinx_pilot_check.py logs: how many drafts passed, and why the others did not
The listings are then run through relinx_pilot_check.py (test instance: the real intake rules, a few cents of Claude each, no video); the survivors are the population.
"""
import re
import sys
import time

import requests

AGENCY = "https://relinx.it/it/agenzia/Gial/immobili/"
UA = {"User-Agent": "Mozilla/5.0"}
KEEP = ("appartamento", "attico")


def ids_from_agency_page(html: str) -> list:
    seen, out = set(), []
    for m in re.finditer(r"/it/agenzia/Gial/immobili/(\d{3,5})/", html):
        if m.group(1) not in seen:
            seen.add(m.group(1)); out.append(m.group(1))
    return out


def canonical_of(html: str) -> str:
    for pat in (r'property="og:url"\s+content="([^"]+)"', r'content="([^"]+)"\s+property="og:url"', r'rel="canonical"\s+href="([^"]+)"', r'href="([^"]+)"\s+rel="canonical"'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return ""


def kind_of(url: str) -> str:
    m = re.search(r"/([a-z]+)-(?:vendita|affitto)-", url)
    return m.group(1) if m else ""


def classify(reason: str) -> str:
    r = reason.lower()
    if "vuote" in r and "etichett" in r:
        return "stanze vuote senza etichette"
    if "illustr" in r or "render" in r:
        return "illustrazioni/render"
    if "foto utilizzabili" in r:
        return "poche foto/ambienti utilizzabili"
    if "timeout" in r or "readtimeout" in r:
        return "timeout del sito"
    if "qualit" in r:
        return "qualita' foto"
    return "altro: " + reason[:80]


def parse_log(text: str) -> dict:
    """{'passed': [(label, job)], 'failed': [(label, reason_class, reason)]} from a relinx_pilot_check.py log (the draft_check report at the end)."""
    passed, failed, cur = [], [], None
    for line in text.splitlines():
        m = re.match(r"\[(PASS|WARN|FAIL)\] (.+?) \(([0-9a-f]{8}|-)\) mode=", line)
        if m:
            cur = [m.group(1), m.group(2), m.group(3), ""]
            if m.group(1) != "FAIL":
                passed.append((m.group(2), m.group(3))); cur = None
            else:
                failed.append(cur)
            continue
        if cur and not cur[3]:
            mm = re.match(r"\s+FAIL\s+\S+\s+(.*)", line)
            if mm:
                cur[3] = mm.group(1)
    return {"passed": passed, "failed": [(f[1], classify(f[3]), f[3]) for f in failed]}


def cmd_list(out, exclude):
    html = requests.get(AGENCY, headers=UA, timeout=60).text
    ids = [i for i in ids_from_agency_page(html) if i not in exclude]
    print(f"{len(ids)} listings on the agency page (after exclusions)", flush=True)
    kept = []
    for i in ids:
        try:
            page = requests.get(f"https://relinx.it/it/agenzia/Gial/immobili/{i}/", headers=UA, timeout=60).text
        except Exception as e:
            print(i, "read failed", repr(e)[:80]); continue
        url = canonical_of(page)
        k = kind_of(url)
        if url and k in KEEP:
            kept.append(f"{url} | {i} {url.rstrip('/').rsplit('/', 1)[-1][:40]}")
        time.sleep(1)
    open(out, "w").write("\n".join(kept) + "\n")
    print(f"{len(kept)} apartments written to {out}")
    return 0


def cmd_report(logs):
    passed, failed = [], []
    for p in logs:
        r = parse_log(open(p, errors="replace").read())
        passed += r["passed"]; failed += r["failed"]
    total = len(passed) + len(failed)
    print(f"{len(passed)} passed of {total} checked")
    for label, job in passed:
        print("  PASS", label, job)
    by = {}
    for label, cls, _ in failed:
        by.setdefault(cls, []).append(label.split()[0])
    for cls, labels in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(labels):3d} {cls}: {' '.join(labels)}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "list":
        ex = set(a[a.index("--exclude") + 1].split(",")) if "--exclude" in a else set()
        sys.exit(cmd_list(a[1], ex))
    if len(a) >= 2 and a[0] == "report":
        sys.exit(cmd_report(a[1:]))
    print(__doc__)
