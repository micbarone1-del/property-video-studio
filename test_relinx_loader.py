import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image
import relinx_pilot_check as rc
res = []


def check(n, ok, info=""):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else " -- " + str(info)))


def full(pid):
    return "/it/immobili/foto/%s/thumb/?variant=full&amp;v=1791147101" % pid


def card(pid):
    return "/it/immobili/foto/%s/thumb/?variant=card&amp;v=1791147101" % pid


graph = {"@context": "x", "@graph": [{"@type": "WebPage"}, {"@type": "Apartment", "name": "Attico Albano", "identifier": "1307",
                                                              "description": "Nel cuore del centro storico, attico luminoso."}]}
page = ('<script type="application/ld+json">' + json.dumps(graph) + "</script>"
        + "".join('<img data-src="%s">' % full(i) for i in (3011, 3010, 3012, 3010))
        + '<img src="%s"><img src="%s">' % (card(777), card(778)))
L = rc.parse_listing(page, "https://relinx.it/it/immobili/albano/appartamento-vendita-110-mq-3-locali-1307/")
check("P1 id is the number at the end of the URL", L["id"] == "1307", L["id"])
check("P2 description and name come from the listing node of the graph", L["description"].startswith("Nel cuore") and L["name"] == "Attico Albano", L)
check("P3 gallery photos only, no duplicates, in page order", [p.split("/")[4] for p in L["photos"]] == ["3011", "3010", "3012"], L["photos"])
check("P4 related listings (variant=card) are ignored", not any("777" in p or "778" in p for p in L["photos"]))
og = '<meta property="og:description" content="Scopri appartamento a Roma &amp; dintorni">' + full(55)
L2 = rc.parse_listing(og, "https://relinx.it/x/y-55/")
check("P5 falls back to og:description when the graph has no listing node", L2["description"].startswith("Scopri") and "&amp;" not in L2["description"], L2)
try:
    rc.parse_listing("<html></html>", "https://relinx.it/x/y-9/")
    check("P6 a page with no description is an error, not an empty job", False)
except ValueError:
    check("P6 a page with no description is an error, not an empty job", True)

sq = Image.new("RGB", (400, 400), (255, 255, 255))
sq.paste(Image.new("RGB", (400, 300), (90, 120, 160)), (0, 50))
check("T1 white bands above and below are removed", rc.trim_bands(sq).size == (400, 300), rc.trim_bands(sq).size)
tall = Image.new("RGB", (400, 400), (255, 255, 255))
tall.paste(Image.new("RGB", (280, 400), (90, 120, 160)), (60, 0))
check("T2 white bands left and right are removed (portrait photo)", rc.trim_bands(tall).size == (280, 400), rc.trim_bands(tall).size)
full = Image.new("RGB", (400, 300), (90, 120, 160))
check("T3 a photo with no padding is left alone", rc.trim_bands(full).size == (400, 300))
white = Image.new("RGB", (400, 300), (255, 255, 255))
check("T4 an all-white image is left alone (no crash)", rc.trim_bands(white).size == (400, 300))
bright = Image.new("RGB", (400, 300), (252, 250, 249))
bright.paste(Image.new("RGB", (400, 20), (90, 90, 90)), (0, 140))
check("T5 a bright room photo (off-white, not pure white) is not cropped to a thin strip", rc.trim_bands(bright).size[1] >= 150, rc.trim_bands(bright).size)

import tempfile
pf = os.path.join(tempfile.mkdtemp(), "req.json")
json.dump({"external_ref": "crm-710-abc", "agency_name": "GIAL", "description": "d", "photos": [{"url": "https://cdn/x.jpg", "category": "living"}], "callback_url": "https://real.partner/hook"}, open(pf, "w"))
q = rc.payload_from_file(pf, "http://127.0.0.1:9")
check("R1 partner request file: callback goes to the local receiver, never to the real partner", q["callback_url"] == "http://127.0.0.1:9/hook", q["callback_url"])
check("R2 fresh external_ref per run, photos and categories untouched", q["external_ref"].startswith("T-crm-710-abc-") and q["photos"][0]["category"] == "living" and q["photos"][0]["url"] == "https://cdn/x.jpg", q)
json.dump({"external_ref": "x", "agency_name": "g", "description": "", "photos": []}, open(pf, "w"))
try:
    rc.payload_from_file(pf, "http://127.0.0.1:9")
    check("R3 an incomplete partner request file is refused", False)
except ValueError:
    check("R3 an incomplete partner request file is refused", True)
print("%d/%d" % (sum(res), len(res)))
sys.exit(0 if all(res) else 1)
