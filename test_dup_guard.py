import listing_registry as lr
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n)
    F += (not c)
U = "https://relinx.it/it/immobili/marino/appartamento-vendita-90-mq-4-locali-1101/"
chk("G1 number from a listing URL", lr.listing_of_url(U) == "1101")
chk("G2 number with query string", lr.listing_of_url(U.rstrip("/") + "?x=1") == "1101")
chk("G3 URL without number", lr.listing_of_url("https://example.com/casa/") is None and lr.listing_of_url("") is None)
R = lambda j, st, res="360p", l="1101": {"listing": l, "job_id": j, "where": "test", "status": st, "resolution": res}
recs = [R("a", "draft"), R("b", "failed"), R("c", "done"), R("d", "awaiting_approval"), R("e", "draft", l="9999")]
chk("G4 open: draft and awaiting_approval only", [r["job_id"] for r in lr.open_jobs("1101", recs)] == ["a", "d"])
chk("G5 exclude_job", [r["job_id"] for r in lr.open_jobs("1101", recs, exclude_job="a")] == ["d"])
d = lr.duplicates("1101", "1080p", recs)
chk("G6 360p done does not block 1080p, open reported", d["done"] == [] and len(d["open"]) == 2)
chk("G7 360p done blocks a 360p run", [r["job_id"] for r in lr.duplicates("1101", "360p", recs)["done"]] == ["c"])
chk("G8 other listing untouched", lr.duplicates("1234", "360p", recs) == {"open": [], "done": []})
print("FAILS", F)
