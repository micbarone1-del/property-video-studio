"""2026-11-20: possible duplicate of a partner request (same listing, different external_ref): pure logic + source guards on the hook. No network."""
import os, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.getcwd())
import partner_duplicates as pd
ok = True
def chk(name, cond, info=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if (info and not cond) else ""))
    if not cond: ok = False
NOW = datetime(2026, 11, 20, 12, 0, 0)
def photos(names, sig="S1"):
    return [{"url": f"https://store.example/b/{n}.jpg?X-Signature={sig}", "order": i} for i, n in enumerate(names)]
def job(ref, agency="ag1", ph=None, desc="Trilocale luminoso con balcone", name="Via Roma 12", status="draft", created=NOW, source="relinx"):
    return {"source": source, "agency_id": agency, "external_ref": ref, "status": status, "created_at": created.isoformat(), "property_name": name,
            "partner_payload": {"photos": ph if ph is not None else photos(list("abcdef")), "description": desc}}
base = job("R1")
chk("PD1 same agency, same photos, different external_ref: duplicate by photos", pd.same_listing(job("R2", ph=photos(list("abcdef"), "S2")), base) == "stesse foto (100%)")
chk("PD2 a re-signed URL (another query string) still matches", pd.same_listing(job("R2", ph=photos(list("abcdef"), "OTHER"), desc="x", name="y"), base) is not None)
chk("PD3 4 of 5 photos shared (80%) is a duplicate, 3 of 5 (60%) is not",
    pd.same_listing(job("R2", ph=photos(list("abcdz")), desc="x", name="y"), job("R1", ph=photos(list("abcde")), desc="q", name="w")) is not None
    and pd.same_listing(job("R2", ph=photos(list("abxyz")), desc="x", name="y"), job("R1", ph=photos(list("abcde")), desc="q", name="w")) is None)
chk("PD4 different photos but same title and description: duplicate by text", pd.same_listing(job("R2", ph=photos(list("uvwxyz"))), base) == "stesso titolo e stessa descrizione")
chk("PD5 different agency: never a duplicate", pd.same_listing(job("R2", agency="ag2"), base) is None)
chk("PD6 same external_ref is NOT handled here (the idempotency check does it)", pd.same_listing(job("R1"), base) is None)
chk("PD7 fewer than 3 photos: photo rule off; different text: no duplicate", pd.same_listing(job("R2", ph=photos(["a", "b"]), desc="x", name="y"), job("R1", ph=photos(["a", "b"]), desc="q", name="w")) is None)
chk("PD8 missing description or title: text rule off", pd.same_listing(job("R2", ph=photos(list("uvwxyz")), desc=""), job("R1", ph=photos(list("abcdef")), desc="")) is None)
jobs = {"old": job("R1"), "new": job("R2")}
r = pd.find_possible_duplicates("new", jobs, NOW)
chk("PD9 find: reports the earlier job with id, external_ref, status, reason", len(r) == 1 and r[0]["job_id"] == "old" and r[0]["external_ref"] == "R1" and r[0]["status"] == "draft" and r[0]["reason"])
chk("PD10 a failed earlier job is ignored", pd.find_possible_duplicates("new", {"old": job("R1", status="failed"), "new": job("R2")}, NOW) == [])
chk("PD11 an earlier job older than 30 days is ignored", pd.find_possible_duplicates("new", {"old": job("R1", created=NOW - timedelta(days=31)), "new": job("R2")}, NOW) == [])
chk("PD12 a non-partner job is ignored and a job is never its own duplicate", pd.find_possible_duplicates("new", {"old": job("R1", source="manual"), "new": job("R2")}, NOW) == [] and pd.find_possible_duplicates("zz", jobs, NOW) == [])
chk("PD13 a job without a readable payload does not break anything", pd.find_possible_duplicates("new", {"old": {"source": "relinx", "agency_id": "ag1", "external_ref": "R1", "status": "draft", "partner_payload": "x"}, "new": job("R2")}, NOW) == [])
html = pd.alert_html("newid", {"external_ref": "R2", "property_name": "Via Roma 12"}, r)
chk("PD14 the alert names both jobs, both external_refs and the reason, in Italian", "newid" in html and "old" in html and "R1" in html and "R2" in html and "stesse foto" in html and "doppione" in html)
src = open("api_server.py", encoding="utf-8").read()
i = src.index("async def create_video_from_partner"); j = src.index("async def _build_relinx_job_in_background")
fn = src[i:j]
k = fn.index("partner_duplicates.find_possible_duplicates")
chk("PD15 the hook runs after the job is saved and BEFORE the background build starts, inside try/except", fn.index("_save_job(job_id)") < k < fn.index("background_tasks.add_task(_build_relinx_job_in_background") and "except Exception" in fn[k:fn.index("background_tasks.add_task(_build_relinx_job_in_background")])
hook = fn[fn.rindex("try:", 0, k):fn.index("background_tasks.add_task(_build_relinx_job_in_background")]
chk("PD16 the hook never blocks or changes the job: no raise, no status change, no return", "raise" not in hook and '["status"]' not in hook and "return" not in hook)
chk("PD17 the same external_ref is still answered by the idempotency check BEFORE job creation", fn.index("existing_id, existing = next(") < fn.index('"source": "relinx",'))
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
