"""download_selected_photos: transient failures are retried in rounds, order is kept, permanent failures are reported with the real error."""
import sys, tempfile
from pathlib import Path
import listing_scraper as ls
ls.DOWNLOAD_RETRY_WAITS = (0, 0)
res = []
def t(n, ok): res.append(ok); print(("PASS " if ok else "FAIL ") + n)

def make():
    return {"selected": {"living": [{"url": "L0"}, {"url": "L1"}], "kitchen": [{"url": "K0"}]}, "gaps": []}

def run(fail_plan):
    calls = {}
    def fake(url, d, stem, fb=None):
        calls[url] = calls.get(url, 0) + 1
        if calls[url] <= fail_plan.get(url, 0):
            return {"ok": False, "path": None, "error": f"boom {url}", "url_used": None, "used_fallback": False}
        return {"ok": True, "path": f"/x/{stem}.jpg", "error": None, "url_used": url, "used_fallback": False}
    ls.download_photo = fake
    return ls.download_selected_photos(make(), Path(tempfile.mkdtemp())), calls

r, c = run({})
t("R1 all ok: nothing dropped, one call each", not r["download_failures"] and set(c.values()) == {1} and len(r["selected"]["living"]) == 2)
r, c = run({"L0": 1, "K0": 2})
t("R2 transient failures recovered in later rounds", not r["download_failures"] and c["L0"] == 2 and c["K0"] == 3 and c["L1"] == 1)
t("R3 order kept inside the category", [p["url"] for p in r["selected"]["living"]] == ["L0", "L1"])
r, c = run({"L1": 99})
t("R4 permanent failure dropped after 3 rounds with real error", c["L1"] == 3 and r["download_failures"] == [{"category": "living", "url": "L1", "error": "boom L1"}] and [p["url"] for p in r["selected"]["living"]] == ["L0"])
r, c = run({"L0": 99, "L1": 99, "K0": 99})
t("R5 total failure reported for all three", len(r["download_failures"]) == 3 and r["selected"]["living"] == [] and r["selected"]["kitchen"] == [])
print(f"{sum(res)}/{len(res)}"); sys.exit(0 if all(res) else 1)
