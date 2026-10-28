import sys
import listing_scraper as ls
res = []


def check(name, ok):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


calls = []
ls._is_hall_photo = lambda url, fb=None: (calls.append(url) or (True, True))
ls._classify_photo_vision = lambda url, fb=None: ("exterior", True)


def run(photos):
    del calls[:]
    ls.refine_exterior_outdoor_with_vision(photos)
    return photos


p = run([{"url": "a", "label_it": "Soggiorno", "category": "living"}])
check("L1 a living photo WITH a caption keeps its label (vision is not asked)", p[0]["category"] == "living" and calls == [])
p = run([{"url": "b", "label_it": "", "category": "living"}])
check("L2 a living photo WITHOUT a caption is still checked and a hall leaves the living slot", p[0]["category"] == "uncategorized" and calls == ["b"])
p = run([{"url": "c", "label_it": "   ", "category": "living"}])
check("L3 a caption of only spaces counts as no caption", calls == ["c"])
p = run([{"url": "d", "category": "living"}])
check("L4 a photo without the label_it key counts as no caption", calls == ["d"])
src = open("listing_scraper.py").read()
check("L5 the only hall-check call site is the one with the caption rule", src.count("_is_hall_photo(") == 2 and "label_it" in src.split("living = [p for p in photos")[1][:400])
print(str(sum(res)) + "/" + str(len(res)))
sys.exit(0 if all(res) else 1)
