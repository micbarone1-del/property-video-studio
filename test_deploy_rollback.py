"""2026-11-24: the rollback point printed by deploy_relinx_prod.sh. Runs the REAL step-2 block of the script in a temporary git repo."""
import os, re, subprocess, sys, tempfile
ok = True
def chk(n, c):
    global ok; print(("PASS" if c else "FAIL"), n); ok &= bool(c)
sh = open("deploy_relinx_prod.sh", encoding="utf-8").read()
blk = re.search(r'step "2/7 rollback point"\n(.*?)\nstep "3/7', sh, re.S).group(1)
d = tempfile.mkdtemp()
def git(*a): return subprocess.run(["git", "-C", d, *a], capture_output=True, text=True, check=True).stdout.strip()
git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
open(d + "/f", "w").write("1"); git("add", "f"); git("commit", "-q", "-m", "one"); c1 = git("rev-parse", "HEAD")
open(d + "/f", "w").write("2"); git("commit", "-q", "-am", "two"); c2 = git("rev-parse", "HEAD")
open(d + "/f", "w").write("3"); git("commit", "-q", "-am", "three"); c3 = git("rev-parse", "HEAD")
def run(last, manual):
    L, M = d + "/last.txt", d + "/manual.txt"
    for f in (L, M):
        if os.path.exists(f): os.remove(f)
    if last: open(L, "w").write(last + "\n")
    if manual: open(M, "w").write(manual + "\n")
    script = "step(){ echo \"STEP $1\"; }\nstop(){ echo \"STOPPED: $1\"; exit 7; }\ncd %s\n%s\n" % (d, blk)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=dict(os.environ, PVS_LAST_DEPLOYED_FILE=L, PVS_ROLLBACK_FILE=M))
    return r.returncode, r.stdout, (open(M).read().strip() if os.path.exists(M) else None)
rc, out, man = run(c2, c1)
chk("R1 the commit recorded by the previous deploy wins over a stale hand-written file", rc == 0 and ("rollback commit: " + c2) in out and c1 not in out.split("source")[0])
chk("R2 the old hand-written file is kept in sync", man == c2)
rc, out, man = run(None, c1)
chk("R3 without the recorded file the hand-written one is used and flagged NOT verified", rc == 0 and ("rollback commit: " + c1) in out and "NOT verified" in out)
rc, out, _ = run(None, None)
chk("R4 no rollback point at all: the deploy stops", rc == 7 and "no rollback point" in out)
rc, out, _ = run("0123456789abcdef0123456789abcdef01234567", None)
chk("R5 a rollback commit that is not in the repository stops the deploy", rc == 7 and "not in this repository" in out)
rc, out, _ = run(c3, None)
chk("R6 rollback equal to HEAD is announced", rc == 0 and "same as HEAD" in out)
chk("R7 the script records the deployed commit only at the very end, after the health check", sh.index('git rev-parse HEAD > "$LAST_FILE"') > sh.index('step "7/7') and sh.index('git rev-parse HEAD > "$LAST_FILE"') < sh.index("DEPLOY DONE"))
chk("R8 the final listing shows DEFAULT_VOICE and FACT_MASK", "DEFAULT_VOICE|FACT_MASK" in sh)
print("RESULT:", "ALL PASS" if ok else "FAILURES"); sys.exit(0 if ok else 1)
