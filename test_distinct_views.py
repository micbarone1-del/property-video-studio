"""2026-11-12: a second photo of a room shows a different view than the first (listing 105: first and last scene were the same garden). No network, no key."""
import os, sys, types
sys.path.insert(0, os.getcwd())
try:
    import anthropic  # noqa
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import listing_scraper as ls
res = []
def check(name, ok, info=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  [%s]" % (info,)))
def mk(*n): return [{"url": x} for x in n]
def run(same, names=("a", "b", "c", "d", "e"), cat="outdoor"):
    asked = []
    def chk(c, head, p):
        asked.append((head["url"], p["url"])); return same.get(p["url"])
    by = {cat: mk(*names)}
    summ = ls.order_distinct_views(by, check=chk)
    return [p["url"] for p in by[cat]], asked, summ, by
order, asked, summ, by = run({"b": True, "c": False, "d": False})
check("D1 head stays first; a photo with the SAME view as the head moves behind the distinct ones", order == ["a", "c", "d", "e", "b"], order)
check("D2 only the cheap number of candidates is compared, each with the head", asked == [("a", "b"), ("a", "c"), ("a", "d")], asked)
check("D3 the answer is on the photo (True / False; not asked = missing) and the summary counts", by["outdoor"][4]["same_view_as_first"] is True and by["outdoor"][1]["same_view_as_first"] is False and "same_view_as_first" not in by["outdoor"][3] and summ["outdoor"] == {"checked": 3, "same_view": 1}, summ)
order, asked, summ, by = run({"b": True, "c": True, "d": True})
check("D4 every compared photo is the same view -> they go behind the one not compared, nothing deleted", order == ["a", "e", "b", "c", "d"] and summ["outdoor"]["same_view"] == 3 and len(order) == 5, order)
order, asked, summ, by = run({"b": True, "c": True}, names=("a", "b", "c"))
check("D4b ALL candidates are the same view -> order unchanged, all still there (the best is used, the report says same_view)", order == ["a", "b", "c"] and summ["outdoor"]["same_view"] == 2, order)
order, asked, summ, by = run({"b": None, "c": None, "d": None})
check("D5 a failed call (None) keeps the order", order == ["a", "b", "c", "d", "e"], order)
by = {"kitchen": mk("k1")}; asked = []
ls.order_distinct_views(by, check=lambda *a: asked.append(a))
check("D6 a category with one candidate is not asked", asked == [] and [p["url"] for p in by["kitchen"]] == ["k1"])
os.environ["PVS_DISTINCT_VIEWS"] = "0"
by = {"outdoor": mk("a", "b")}; asked = []
check("D7 PVS_DISTINCT_VIEWS=0 switches it off", ls.order_distinct_views(by, check=lambda *a: asked.append(a)) == {"enabled": False} and asked == [])
os.environ["PVS_DISTINCT_VIEWS"] = "1"
def boom(*a): raise RuntimeError("down")
by = {"outdoor": mk("a", "b", "c")}
ls.order_distinct_views(by, check=boom)
check("D8 an exception in the check never breaks the selection", [p["url"] for p in by["outdoor"]] == ["a", "b", "c"])
src = open("listing_scraper.py").read()
body = src[src.index("def _categorize_and_rank_photos("):src.index("QUALITY_RANKING_PROMPT = ")]
check("D9 the ordering is a step of the ONE shared selection step, after the quality filter (standard, premium, URL and Relinx all get it)",
      body.index("filter_poor_quality_candidates(by_category)") < body.index("order_distinct_views(by_category)"))
_rep = ls.build_selection_report([{"url": "S1", "category": "outdoor"}], {"selected": {"outdoor": [{"url": "S1"}, {"url": "S2", "same_view_as_first": True}]}, "total_selected": 2})
check("D10 the selection report carries same_view_as_first per selected photo", [x["same_view_as_first"] for x in _rep["selected"]["outdoor"]] == [None, True], _rep["selected"])
print("%d/%d PASS" % (sum(res), len(res)))
sys.exit(0 if all(res) else 1)
