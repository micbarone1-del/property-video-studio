p = "listing_scraper.py"; s = open(p).read()
R = [
('Return ONLY a JSON array of integers, the photo numbers ordered best to worst, e.g. [3, 1, 2]. No other text.\n',
 'Compare the photos in at most 5 short sentences. Then finish with a final line that contains ONLY the JSON array of integers, the photo numbers ordered best to worst, e.g. [3, 1, 2].\n'),
('client.messages.create(model=RANK_MODEL, max_tokens=200,', 'client.messages.create(model=RANK_MODEL, max_tokens=RANK_MAX_TOKENS,'),
('RANK_MODEL = os.environ.get("PVS_RANK_MODEL", "claude-sonnet-5-5")\n',
 'RANK_MODEL = os.environ.get("PVS_RANK_MODEL", "claude-sonnet-5-5")\n'
 '# 2026-11-12: measured on listing 105 (6 runs): Sonnet writes its comparison BEFORE the list, 200 tokens cut it off 5 times of 6 (stop_reason max_tokens) and the\n'
 '# ranking silently fell back to the original order. The prompt now asks for a short comparison and the list on the LAST line; the parser takes the LAST list.\n'
 'RANK_MAX_TOKENS = 700\n'),
('''        order_match = re.search(r"\\[[\\d,\\s]+\\]", raw)
        if not order_match:
            return _tag_rank(candidates, "fallback_original_order: unparseable model reply")
        order = json.loads(order_match.group(0))''',
 '''        lists = re.findall(r"\\[\\s*\\d+(?:\\s*,\\s*\\d+)*\\s*\\]", raw)
        if not lists:
            why = "cut off at the token limit" if getattr(response, "stop_reason", None) == "max_tokens" else "no list in the reply"
            log.warning(f"[Scraper] Quality ranking for {category}: {why}: {raw[:200]!r}")
            return _tag_rank(candidates, "fallback_original_order: unparseable model reply (" + why + ")")
        order = json.loads(lists[-1])'''),
]
for o, n in R:
    assert s.count(o) == 1, o[:60]
    s = s.replace(o, n)
open(p, "w").write(s); print("ok")

p = "test_selection_report.py"; s = open(p).read()
anchor = 'res = ls.rank_photos_by_quality("bedrooms", [{"url": "U1", "category": "bedrooms"}])\ncheck("R5 single candidate tagged, no fetch"'
assert s.count(anchor) == 1
new = (
'FakeClient.answer = "Photo 2 is brighter, no mirror. Photo 1 shows a bed (see [1] weaker).\\nPhoto 2 first.\\n[2, 1]"\n'
'calls = install_get({"U1": [Resp(200)], "U2": [Resp(200)]})\n'
'res = ls.rank_photos_by_quality("bedrooms", photos2())\n'
'check("R4b reasoning before the list -> the LAST list is the order, tagged ranked", [p["url"] for p in res] == ["U2", "U1"] and res[0]["rank_status"] == "ranked", res)\n'
'FakeClient.answer = "Photo 2 is brighter and has the bed,"\n'
'calls = install_get({"U1": [Resp(200)], "U2": [Resp(200)]})\n'
'res = ls.rank_photos_by_quality("bedrooms", photos2())\n'
'check("R4c reply with no list -> original order and the status says why", res[0]["rank_status"].startswith("fallback_original_order") and "no list" in res[0]["rank_status"], res[0]["rank_status"])\n'
'check("R4d room for a comparison before the list (>=500 tokens) and the prompt asks for the list on the last line", ls.RANK_MAX_TOKENS >= 500 and "final line" in ls.QUALITY_RANKING_PROMPT and "No other text" not in ls.QUALITY_RANKING_PROMPT)\n')
s = s.replace(anchor, new + anchor); open(p, "w").write(s); print("test ok")
