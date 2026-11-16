"""Partner photo labels (2026-11-16): the 18 captions of Relinx's menu, English names, unknown text, floor plan. Offline, no API call."""
import sys, os, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _n in ("fal_client", "moviepy", "anthropic"):
    if _n not in sys.modules:
        sys.modules[_n] = types.ModuleType(_n)
sys.modules["anthropic"].Anthropic = getattr(sys.modules["anthropic"], "Anthropic", lambda *a, **k: "REAL")
import listing_scraper as s

FAIL = 0
def check(name, cond, info=""):
    global FAIL
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(info)))
    FAIL += (not cond)

RELINX = {"Bagno": "bathrooms", "Balcone": "outdoor", "Camera da letto": "bedrooms", "Cameretta": "bedrooms", "Cantina": "uncategorized",
          "Corridoio": "uncategorized", "Cortile": "outdoor", "Cucina": "kitchen", "Facciata esterna": "exterior", "Garage": "uncategorized",
          "Giardino": "outdoor", "Ingresso": "uncategorized", "Planimetria": "floorplan", "Ripostiglio": "uncategorized", "Salone": "living",
          "Soggiorno": "living", "Terrazzo": "outdoor", "Vista": "outdoor"}
for i, (lab, want) in enumerate(RELINX.items(), 1):
    got = s.partner_photo_category("uncategorized", lab)
    check(f"L{i:02d} {lab} -> {want}", got[0] == want and got[1] == lab, got)
check("L19 lower case + spaces", s.partner_photo_category("uncategorized", "  CUCINA ")[0] == "kitchen")
check("L20 numbered 'Camera da letto 2'", s.partner_photo_category("", "Camera da letto 2")[0] == "bedrooms")
check("L21 accent/punctuation 'Facciata  esterna.'", s.partner_photo_category("", "Facciata  esterna.")[0] == "exterior")
check("L22 english category field", s.partner_photo_category("kitchen")[0] == "kitchen")
check("L23 unknown text stays uncategorized, original kept", s.partner_photo_category("uncategorized", "Bella vista mare") == ("uncategorized", "Bella vista mare", ""))
check("L24 nothing at all", s.partner_photo_category("uncategorized", None, None) == ("uncategorized", "", ""))
check("L25 category wins over caption", s.partner_photo_category("living", "Cucina")[0] == "living")
check("L26 unknown category falls to caption", s.partner_photo_category("zzz", "Bagno")[0] == "bathrooms")
check("L27 plural english", s.partner_photo_category("bathrooms")[0] == "bathrooms")
# floor plan never counts as usable
p = {"url": "u", "category": "uncategorized", "category_source": "partner_floorplan", "label_it": "Planimetria"}
check("L28 floor plan excluded with reason", s.photo_exclusion(p) == "planimetria", s.photo_exclusion(p))
s._describe_cache.clear()
called = []
s.classify_uncategorized_photo = lambda *a, **k: called.append(a) or "living"
s.resolve_uncategorized_photos([p])
check("L29 floor plan is not sent to vision", not called and p["category"] == "uncategorized", (called, p))
q = {"url": "v", "category": "uncategorized", "label_it": "Ingresso"}
s._other_kind = lambda *a, **k: "hall"
s.resolve_uncategorized_photos([q])
check("L30 hall caption still goes to vision", len(called) == 1 and q["category"] == "living", called)
check("L31 usable photo with caption", s.photo_exclusion({"url": "w", "category": "kitchen", "label_it": "Cucina"}) is None)
print("FAILED:", FAIL)
sys.exit(1 if FAIL else 0)
