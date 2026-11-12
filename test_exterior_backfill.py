import os, sys, types
sys.path.insert(0, os.getcwd())
try:
    import anthropic
except Exception:
    m = types.ModuleType("anthropic"); m.Anthropic = object; sys.modules["anthropic"] = m
import listing_scraper as ls
ls.rank_photos_by_quality = lambda cat, p: p
ls.filter_poor_quality_candidates = lambda *a, **k: None
def ph(c, n): return [{"url": "u_%s_%d" % (c, i), "category": c} for i in range(n)]
def seq(*parts): return ls.standard_scene_sequence(ls.select_photos_for_scene_count(sum(parts, []), 6))
base = ph("living", 2) + ph("kitchen", 1) + ph("bedrooms", 1) + ph("bathrooms", 1)
a, b, c = seq(base, ph("outdoor", 2)), seq(base, ph("outdoor", 1)), seq(ph("exterior", 1), base, ph("outdoor", 2))
d = seq(ph("exterior", 2), base)
T = [("E1 senza facciata, 2 esterni: uno apre e uno chiude", a == ["outdoor", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]),
     ("E2 senza facciata, 1 esterno: si raddoppia una stanza come prima", b.count("living") == 2 and b.count("outdoor") == 1),
     ("E3 con facciata e 1 esterno: ordine invariato", c == ["exterior", "living", "kitchen", "bedrooms", "bathrooms", "outdoor"]),
     ("E4 due facciate: una apre e una chiude", d[0] == "exterior" and d[-1] == "exterior" and len(d) == 6)]
bad = 0
for n, ok in T:
    print("PASS" if ok else "FAIL", n); bad += (not ok)
raise SystemExit(bad)
