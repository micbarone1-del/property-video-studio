import os, tempfile
os.environ["PVS_JOBS_DIR"] = tempfile.mkdtemp()
import api_server as a
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n)
    F += (not c)
src = open("api_server.py").read()
low, hi = {"luma_resolution": "360p"}, {"luma_resolution": "1080p"}
a.luma_resolution = lambda: "1080p"
chk("D1 360p blocked on a 1080p instance", a._delivery_block_reason("zz", low) is not None)
chk("D2 1080p goes", a._delivery_block_reason("zz", hi) is None)
a.luma_resolution = lambda: "360p"
chk("D3 the 360p test instance is never blocked", a._delivery_block_reason("zz", low) is None)
chk("D4 manual release takes force, the auto tick skips a blocked job", "force: bool = False" in src and 'not j.get("delivery_blocked")' in src)
chk("D5 one release path: the tick still calls release_job", "await release_job(jid)" in src)
print("FAILS", F)
