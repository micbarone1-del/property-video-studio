import sys
ui=open("ui.html").read(); op=open("operator_page.html").read(); api=open("api_server.py").read()
ok=True
def chk(n,c):
    global ok; print(("PASS" if c else "FAIL"),n); ok&=bool(c)
chk("SN1 UI scene labels are 1-based and keep the file tag", ui.count("Scena ${i+1} <span")==2 and "Scena ${idx+1} (scene_${String(idx)" in ui)
chk("SN2 no 0-based UI label left", "Scena ${i} " not in ui and "Scena ${idx} " not in ui)
chk("SN3 dashboard text list 1-based", "(a.scene + 1)" in op and "'scena ' + a.scene +" not in op)
chk("SN4 progress message 1-based", "scena {i + 1}" in api)
sys.exit(0 if ok else 1)
