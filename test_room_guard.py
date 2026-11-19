import re, sys, types
for _m in ('anthropic','pydub'):
    sys.modules.setdefault(_m, types.ModuleType(_m))
sys.modules['pydub'].AudioSegment=object
import listing_scraper as ls
ok=True
def chk(n,c):
    global ok; print(("PASS" if c else "FAIL"),n); ok&=bool(c)
chk("RG1 all four present -> none missing", ls.missing_core_rooms(["living","kitchen","bedrooms","bathrooms","exterior"])==[])
chk("RG2 facade+hall+bath+bed -> living,kitchen missing", ls.missing_core_rooms(["facade","hall","bathrooms","bedrooms"])==["living","kitchen"])
chk("RG3 empty/None -> unknown, no warning", ls.missing_core_rooms([])==[] and ls.missing_core_rooms(None)==[])
chk("RG4 order stable", ls.missing_core_rooms(["kitchen"])==["living","bedrooms","bathrooms"])
src=open("api_server.py").read()
m=re.search(r"def _missing_rooms_italian\(job, min_missing: int = 2\).*?\n\n\ndef ", src, re.S)
ns={}
exec("import sys\n"+m.group(0)[:-len("\n\n\ndef ")], ns)
f=ns["_missing_rooms_italian"]
chk("RG5 no scenes -> []", f({})==[] and f(None)==[] and f({"scenes_config":[]})==[])
r=f({"scenes_config":[{"category":"facade"},{"category":"bathrooms"}]})
chk("RG6 italian labels", len(r)==3 and all(isinstance(x,str) and x for x in r))
chk("RG7 wired in 3 places", src.count("_missing_rooms_italian(")==4 and '"missing_rooms"' in src)
chk("RG9 scenes without category are unknown", ls.missing_core_rooms([None,None,None])==[] and ls.missing_core_rooms([None,"living"],1)==["kitchen","bedrooms","bathrooms"])
chk("RG10 threshold: one missing room is quiet at 2, shown at 1", ls.missing_core_rooms(["living","bedrooms","bathrooms"],2)==[] and ls.missing_core_rooms(["living","bedrooms","bathrooms"],1)==["kitchen"])
chk("RG11 two missing warn at threshold 2", ls.missing_core_rooms(["living","bedrooms"],2)==["kitchen","bathrooms"])
chk("RG12 alerts use 2, dashboard row uses 1", "def _missing_rooms_italian(job, min_missing: int = 2)" in src and '_missing_rooms_italian(j, 1)' in src)
chk("RG8 advisory only (no status change near guard)", "missing_core_rooms" not in src.split("def check_listing_acceptance")[0] if "def check_listing_acceptance" in src else True)
sys.exit(0 if ok else 1)
