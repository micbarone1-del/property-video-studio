"""test_learning_replay.py - planted signal is found AND confirmed on the future; no-signal data confirms (almost) nothing; read-only. Run: python3 test_learning_replay.py"""
import random, sys, ast, os
import learning_replay as lr, learning_loop as ll
F = 0
def chk(n, ok, info=""):
    global F
    print(("PASS " if ok else "FAIL ") + n + (" " + str(info) if info and not ok else ""))
    F += 0 if ok else 1
def mk(n, signal, seed):
    rnd = random.Random(seed); rows = []
    for i in range(n):
        job = f"job{i // 3}"
        cat = rnd.choice(["living", "kitchen", "bedroom", "bath"]); mv = rnd.choice(["a", "b", "c"])
        p = (0.7 if (signal and cat == "kitchen" and mv == "b") else 0.15)
        rows.append({"job": job, "scene": f"s{i}", "split": ll.split_of(job), "cat": cat, "move": mv, "tier": "luma", "plan_kind": "forward", "anchor_kind": "specific",
                     "depth": "?", "l_qc": rnd.random() < p, "l_persistent": None, "l_detector": None})
    return rows
rows = mk(600, True, 1)
rec = lr.replay(rows, "l_qc", ll.FEATURES, 120, 60); s = lr.summarise(rec)
chk("R1 planted signal: found on the past and confirmed on the future", s["found"]["confirmed"] >= 1, s)
null_runs = [lr.summarise(lr.replay(lr.shuffled(mk(600, False, 10 + k), "l_qc", k), "l_qc", ll.FEATURES, 120, 60)) for k in range(6)]
conf = [x["holding"]["confirmed"] for x in null_runs]
chk("R2 no-signal data: in most runs (>=4 of 6) nothing held on the past is confirmed on the future", sum(1 for c in conf if c == 0) >= 4, conf)
print("   null distinct confirmed per run:", conf, "(a non-zero run is ONE chance pattern plus its redundant refinements: the method can be fooled by chance, which is why phase 3 shadow exists)")
chk("R3 too little data -> no checkpoints", lr.replay(rows[:50], "l_qc", ll.FEATURES, 120, 60) == [])
chk("R4 shuffled labels keep the same total of positives", sum(r["l_qc"] for r in lr.shuffled(rows, "l_qc")) == sum(r["l_qc"] for r in rows))
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "learning_replay.py")).read()
chk("R5 read-only: no file writes", "write_text" not in src and "open(" not in src and ".write(" not in src)
import glob
prod = [f for f in glob.glob("*.py") if not f.startswith(("test_", "exp_", "learning_"))]
chk("R6 not imported by production", all("learning_replay" not in open(f, encoding="utf-8", errors="ignore").read() for f in prod))
d = lr.details(rec)
chk("R7 details: one entry per distinct rule, windows listed in order", d and all(isinstance(v, list) and v for v in d.values()) and any("kitchen" in k and "move=b" in k for k in d), list(d)[:4])
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf): lr.print_details(rec)
chk("R8 print_details prints one line per rule", len(buf.getvalue().strip().splitlines()) == len(d))
print("FAILS", F); sys.exit(1 if F else 0)
