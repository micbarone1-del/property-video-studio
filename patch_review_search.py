"""One-off, idempotent patcher: adds (1) /clip-review page, (2) search on /operator/status?q= and a search box on the operator page. Prints what it changed."""
import re
from pathlib import Path

def sub(path, old, new, marker):
    p = Path(path); t = p.read_text(encoding="utf-8")
    if marker in t:
        print("gia presente:", path, marker); return
    assert t.count(old) == 1, f"{path}: anchor not found exactly once: {old[:50]}"
    p.write_text(t.replace(old, new), encoding="utf-8"); print("patched:", path, marker)

A = "api_server.py"
sub(A, '''    if (path in ("/", "", "/health", "/operator-page")''', '''    if (path in ("/", "", "/health", "/operator-page", "/clip-review")''', '"/clip-review")')
sub(A, '''@app.get("/operator-page", response_class=FileResponse)''', '''@app.get("/clip-review", response_class=FileResponse)
def clip_review_page():
    return FileResponse(BASE_DIR / "clip_review.html", headers={"Cache-Control": "no-cache"})


@app.get("/operator-page", response_class=FileResponse)''', 'def clip_review_page')
sub(A, '''async def operator_status():''', '''async def operator_status(q: str = ""):''', 'operator_status(q: str')
sub(A, '''        if now - created > timedelta(hours=72) and j.get("status") == "done" and not j.get("review_pending"):
            continue
        det, aw =''', '''        ql = (q or "").strip().lower()
        if ql:   # search: ANY job, any age (job id, listing number or name)
            if ql not in jid.lower() and ql not in str(_listing_number(j, jid) or "").lower() and ql not in str(j.get("property_name") or "").lower():
                continue
        elif now - created > timedelta(hours=72) and j.get("status") == "done" and not j.get("review_pending"):
            continue
        det, aw =''', 'search: ANY job')
sub(A, '''"jobs": rows[:80]}''', '''"jobs": rows[:(300 if (q or "").strip() else 80)]}''', 'rows[:(300')
O = "operator_page.html"
sub(O, '''  <div id="err"></div>''', '''  <input id="q" placeholder="Cerca: id job, numero annuncio o nome (invio)" style="width:100%;padding:8px;margin:0 0 10px;border-radius:8px;border:1px solid var(--line);font:inherit" onkeydown="if(event.key==='Enter'){Q=this.value.trim();load();}">
  <div id="err"></div>''', 'id="q"')
sub(O, '''let FILTER = '';''', '''let FILTER = ''; let Q = '';''', "let Q = ''")
sub(O, '''await api('/operator/status');''', '''await api('/operator/status' + (Q ? '?q=' + encodeURIComponent(Q) : ''));''', "'?q=' + encodeURIComponent")
