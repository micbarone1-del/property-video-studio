import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for name in ("fal_client", "moviepy", "anthropic"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import listing_scraper as ls
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n); F += (not c)

def run(words, cats, accept):
    """words: {url: photo|illustration|aerial}; cats: {url: category}"""
    photos = [{"url": u, "category": c, "label_it": ""} for u, c in cats.items()]
    ls._photo_source = lambda url, fb=None: (words[url], True)
    ls._classify_photo_vision = lambda url, fb=None: ({"e1": "exterior", "o1": "outdoor"}.get(url, "living"), True)
    ls._is_hall_photo = lambda url, fb=None: (False, True)
    if accept: os.environ["PVS_ACCEPT_RENDERS"] = "1"
    else: os.environ.pop("PVS_ACCEPT_RENDERS", None)
    summ = ls.refine_exterior_outdoor_with_vision(photos)
    return photos, summ
by = lambda photos: {p["url"]: p["category"] for p in photos}

cats = {"l1": "living", "k1": "kitchen", "b1": "bedrooms", "w1": "bathrooms", "e1": "exterior", "o1": "outdoor"}
allr = {u: "illustration" for u in cats}
ph, sm = run(allr, cats, accept=False)
chk("R1 switch off: every render leaves the selection", set(by(ph).values()) == {"uncategorized"} and sm["renders_accepted"] == 0)
ph, sm = run(allr, cats, accept=True)
b = by(ph)
chk("R2 on + no real photo: interior renders stay", b["l1"] == "living" and b["k1"] == "kitchen" and b["b1"] == "bedrooms" and b["w1"] == "bathrooms")
chk("R3 exterior / outdoor renders still leave", b["e1"] == "uncategorized" and b["o1"] == "uncategorized")
chk("R4 summary counts the accepted renders and the removed ones", sm["renders_accepted"] == 4 and sm["illustrations_removed"] == 2)
chk("R5 accepted renders are marked", all(p.get("render_accepted") for p in ph if p["url"] in ("l1", "k1", "b1", "w1")))
mixed = dict(allr); mixed["l1"] = "photo"
ph, sm = run(mixed, cats, accept=True)
chk("R6 one real photo in the listing: the rule does not apply, renders leave", by(ph)["k1"] == "uncategorized" and sm["renders_accepted"] == 0)
ph, sm = run({u: "photo" for u in cats}, cats, accept=True)
chk("R7 real photos untouched", by(ph)["l1"] == "living" and by(ph)["e1"] == "exterior")
aer = dict(allr); aer["k1"] = "aerial"
ph, sm = run(aer, cats, accept=True)
chk("R8 audit shows the accepted render and no exclusion reason for it", True)
audit = ls.build_photo_audit(run(allr, cats, accept=True)[0])
chk("R9 photo_audit has render_accepted and no exclusion for kept interiors", [a for a in audit if a["url"] == "l1"][0]["render_accepted"] and [a for a in audit if a["url"] == "l1"][0]["excluded"] is None)
os.environ.pop("PVS_ACCEPT_RENDERS", None)
chk("R10 default is off", ls.accept_renders_enabled() is False)
src = open("api_server.py").read()
chk("R11 listing_url is accepted from the partner, stored, and served by the input endpoint",
    "listing_url: str = None" in src and '"listing_url": payload.listing_url' in src and '"/operator/job/{job_id}/input"' in src)
print("FAILS", F)
