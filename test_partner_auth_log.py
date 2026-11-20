import os, sys, tempfile
os.environ["PVS_DATA_DIR"] = tempfile.mkdtemp()
import partner_api
ok = True
def chk(n, c):
    global ok; print(("PASS" if c else "FAIL"), n); ok &= bool(c)
live = partner_api.create_partner("Live"); old = partner_api.create_partner("Old")
partner_api.deactivate_partner(old["partner_id"])
chk("PL1 an active key is identified as active", live["partner_id"] + " (active)" == partner_api.identify_partner_key(live["api_key"]))
chk("PL2 a deactivated key is identified as inactive, with its partner id", old["partner_id"] + " (inactive)" == partner_api.identify_partner_key(old["api_key"]))
chk("PL3 an unknown or empty key is 'unknown'", partner_api.identify_partner_key("pvs_wrong") == "unknown" and partner_api.identify_partner_key(None) == "unknown")
chk("PL4 the identification never contains the key", live["api_key"] not in partner_api.identify_partner_key(live["api_key"]))
src = open("api_server.py", encoding="utf-8").read()
i = src.index("async def get_current_partner")
body = src[i:i + 1800]
chk("PL5 every 401 of the partner dependency writes one log line (no Bearer header, refused key)", body.count("[PartnerAuth] 401") == 2 and body.count("log.warning(") == 2)
chk("PL6 the log line carries path, caller address, key length and the identification, never the key", "ip={ip}" in body and "key_len=" in body and "identify_partner_key(raw_key)" in body and "{raw_key}" not in body)
chk("PL7 production log is appended, not overwritten, at restart", "tee -a /tmp/property-video.log" in open("start.sh", encoding="utf-8").read())
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
