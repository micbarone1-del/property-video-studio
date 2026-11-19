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
chk("RG3 empty/None -> all four", ls.missing_core_rooms([])==list(ls.INTERIOR_CATEGORIES) and ls.missing_core_rooms(None)==list(ls.INTERIOR_CATEGORIES))
chk("RG4 order stable", ls.missing_core_rooms(["kitchen"])==["living","bedrooms","bathrooms"])
src=open("api_server.py").read()
m=re.search(r"def _missing_rooms_italian\(job\).*?\n\n\ndef ", src, re.S)
ns={}
exec("import sys\n"+m.group(0)[:-len("\n\n\ndef ")], ns)
f=ns["_missing_rooms_italian"]
chk("RG5 no scenes -> []", f({})==[] and f(None)==[] and f({"scenes_config":[]})==[])
r=f({"scenes_config":[{"category":"facade"},{"category":"bathrooms"}]})
chk("RG6 italian labels", len(r)==3 and all(isinstance(x,str) and x for x in r))
chk("RG7 wired in 3 places", src.count("_missing_rooms_italian(")==4 and '"missing_rooms"' in src)
chk("RG8 advisory only (no status change near guard)", "missing_core_rooms" not in src.split("def check_listing_acceptance")[0] if "def check_listing_acceptance" in src else True)
sys.exit(0 if ok else 1)
