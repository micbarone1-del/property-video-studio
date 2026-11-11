import video_generation as vg
F = 0
def chk(n, c):
    global F
    print(("PASS " if c else "FAIL ") + n)
    F += (not c)
vg.time.sleep = lambda s: None
calls = {"n": 0}
def flaky(fail_times):
    def f(path):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise RuntimeError("502 Bad Gateway")
        return "https://x/ok"
    return f
vg.fal_client.upload_file = flaky(2)
chk("U1 two 502 then ok -> url", vg._upload_bytes(b"x") == "https://x/ok" and calls["n"] == 3)
calls["n"] = 0
vg.fal_client.upload_file = flaky(9)
try:
    vg._upload_bytes(b"x"); r = False
except RuntimeError:
    r = calls["n"] == 3
chk("U2 always failing -> raises after 3 attempts", r)
calls["n"] = 0
vg.fal_client.upload_file = flaky(0)
chk("U3 first try ok -> one call", vg._upload_bytes(b"x") == "https://x/ok" and calls["n"] == 1)
print("FAILS", F)
