"""test_gial_drafts.py - offline checks of gial_drafts (fake HTTP session, no network, nothing started)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gial_drafts as gd
fails = 0
def check(n, c):
    global fails
    print(("PASS " if c else "FAIL ") + n); fails += 0 if c else 1
class R:
    def __init__(self, code, js): self.status_code, self._j, self.text = code, js, str(js)
    def json(self): return self._j
class S:
    def __init__(self, plan): self.plan, self.posts, self.gets, self.n = plan, [], [], {}
    def post(self, url, data=None, timeout=0):
        self.posts.append((url, data)); return R(200, {"job_id": f"j{len(self.posts)}", "status": "preparing"})
    def get(self, url, timeout=0):
        jid = url.rsplit("/", 1)[1]; self.gets.append(jid); self.n[jid] = self.n.get(jid, 0) + 1
        return R(200, self.plan[jid](self.n[jid]))
logs = []
plan = {"j1": lambda n: {"status": "preparing"} if n < 2 else {"status": "draft", "property_name": "A"},
        "j2": lambda n: {"status": "prep_failed", "reason": {"code": "too_few_photos"}},
        "j3": lambda n: {"status": "draft", "property_name": "C"}}
s = S(plan)
res = gd.run([("u1", "one"), ("u2", "two"), ("u3", "three")], s=s, sleep=lambda x: None, out=lambda *a: logs.append(" ".join(map(str, a))))
check("D1 drafts returned, a refused listing is reported and does not stop the others", res == {"u1": "j1", "u2": "refused:prep_failed", "u3": "j3"})
check("D2 only /jobs/from-url is called: never start-generation", all(u.endswith("/jobs/from-url") for u, _ in s.posts) and len(s.posts) == 3)
check("D3 agency and tier are sent, property name left to the app", s.posts[0][1]["agency_id"] == "ag_abea5414" and s.posts[0][1]["model_tier"] == "luma" and s.posts[0][1]["property_name"] == "")
check("D4 job ids for gial_start printed without the refused one", any(l.endswith("j1,j3") for l in logs))
check("D5 refusal reason shown", any("too_few_photos" in l for l in logs))
class S429(S):
    def post(self, url, data=None, timeout=0): return R(429, "Too many requests")
logs.clear(); res = gd.run([("u1", "one"), ("u2", "two")], s=S429({}), sleep=lambda x: None, out=lambda *a: logs.append(" ".join(map(str, a))))
check("D6 a 429/error stops the batch (no hammering)", res == {"u1": "refused:429"})
p = tempfile.mktemp(); open(p, "w").write("# c\nhttps://a/1 | one\n\nhttps://b/2\n")
check("D7 list reader: comments and blanks skipped, label optional", gd.read_list(p) == [("https://a/1", "one"), ("https://b/2", "")])
print("FAILS:", fails); sys.exit(1 if fails else 0)
