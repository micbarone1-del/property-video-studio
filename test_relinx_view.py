import os, tempfile
import listing_registry as lr
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n)
    F += (not c)
R = lambda j, st, res="360p", l="1101", w="test": {"listing": l, "job_id": j, "where": w, "status": st, "resolution": res}
recs = [R("a", "draft"), R("b", "failed"), R("c", "done"), R("e", "draft", l="9999"), R("f", "failed", l="7777")]
f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
f.write("# c\nhttps://x/a-vendita-1101/ | 1101 a [vendita] [esito 2026-11-11: prova]\nhttps://x/a-affitto-9999/ | 9999 b [affitto]\n"
        "https://x/a-vendita-7777/ | 7777 c [vendita]\nhttps://x/a-vendita-5555/ | 5555 d [vendita]\n")
f.close()
rows = lr.relinx_view(f.name, recs); os.unlink(f.name)
chk("W1 four rows, comment skipped", len(rows) == 4)
chk("W2 finished 360p test + open + failed + note", rows[0][:5] == ("1101", "vendita", "FINITO 360p (test)", 1, 1) and "esito" in rows[0][5])
chk("W3 open draft, rental", rows[1][1] == "affitto" and rows[1][2].startswith("APERTO (e"))
chk("W4 only failed", rows[2][2] == "SOLO FALLITI (1)")
chk("W5 no job", rows[3][2] == "NESSUN JOB")
print("FAILS", F)
