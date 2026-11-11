import os, tempfile, json
d = tempfile.mkdtemp()
os.environ["PVS_FAKE_DIR"] = d
import fake_providers as fp
f = os.path.join(d, "x.jpg")
open(f, "wb").write(b"abc")
def setf(lst):
    json.dump({"fal_upload": lst}, open(os.path.join(d, "faults.json"), "w"))
def up():
    try:
        return "OK", fp.fake_upload_file(f)
    except RuntimeError as e:
        return "ERR", str(e)
setf(["http_500", "ok"])
a, b, c = up(), up(), up()
T = [("U1 primo caricamento fallisce con http_500", a[0] == "ERR" and "http_500" in a[1]),
     ("U2 secondo riesce e da' un indirizzo", b[0] == "OK" and isinstance(b[1], str)),
     ("U3 lista esaurita: riesce", c[0] == "OK")]
setf(["http_500", "http_500", "http_500"])
r = [up()[0] for _ in range(4)]
T.append(("U4 tre errori di fila, poi riesce", r == ["ERR", "ERR", "ERR", "OK"]))
bad = 0
for n, ok in T:
    print("PASS" if ok else "FAIL", n)
    bad += (not ok)
raise SystemExit(bad)
