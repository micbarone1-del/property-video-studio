"""Italian language check (2026-10-26): unit tests of italian_check.py with a fake Claude. Zero cost."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import italian_check as ic
res = []
def check(n, ok, info=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + n + ("" if ok else f" -- {info}"))

check("P1 parse: clean JSON", ic.parse('{"errors": [{"wrong": "garantono", "fix": "garantiscono"}]}') == [{"wrong": "garantono", "fix": "garantiscono"}])
check("P2 parse: JSON inside a code fence / with text around", ic.parse('Ecco:\n```json\n{"errors": []}\n```') == [])
check("P3 parse: not JSON / wrong shape -> None (never an empty 'all correct')", ic.parse("va bene") is None and ic.parse('{"x": 1}') is None and ic.parse("") is None and ic.parse(None) is None)
T = ["Due camere notte garantono comodità abitativa.", "Il giardino è di 60 metri quadri."]
check("A1 whole-word replacement, other text untouched", ic.apply(T, [{"wrong": "garantono", "fix": "garantiscono"}]) == ["Due camere notte garantiscono comodità abitativa.", T[1]])
check("A2 a capital first letter is kept", ic.apply(["Garantono comfort."], [{"wrong": "garantono", "fix": "garantiscono"}]) == ["Garantiscono comfort."])
check("A3 a word inside a longer word is never touched", ic.apply(["Il garantonomo resta."], [{"wrong": "garantono", "fix": "x"}]) == ["Il garantonomo resta."])
e = ic.usable_errors([{"wrong": "inesistente", "fix": "corretto"}], T)
check("U1 an error whose words are not in the text is ignored (a made-up report)", e == [])
check("U2 a fix equal to the wrong words, or longer than 3 words, is ignored", ic.usable_errors([{"wrong": "garantono", "fix": "Garantono"}, {"wrong": "garantono", "fix": "uno due tre quattro"}], T) == [])
check("U3 words that are in the listing / address / agency name are never 'corrected' (proper names)", ic.usable_errors([{"wrong": "garantono", "fix": "garantiscono"}], T, context="Agenzia Garantono Immobiliare, Via Roma") == [])
check("U4 the same word twice is reported once", len(ic.usable_errors([{"wrong": "garantono", "fix": "garantiscono"}] * 2, T)) == 1)

calls = []
def reply_seq(*rs):
    q = list(rs)
    def f(prompt):
        calls.append(prompt)
        r = q.pop(0)
        if isinstance(r, Exception): raise r
        return r
    return f
calls.clear()
r = ic.proofread(T, reply_seq('{"errors": [{"wrong": "garantono", "fix": "garantiscono"}]}', '{"errors": []}'))
check("R1 error found, fixed, re-checked clean: 2 calls, texts fixed, nothing remaining", r["checked"] and r["texts"][0].count("garantiscono") == 1 and r["remaining"] == [] and len(calls) == 2 and r["fixed"][0]["wrong"] == "garantono", r)
calls.clear()
r = ic.proofread(T, reply_seq('{"errors": []}'))
check("R2 correct text: ONE call, text identical", r["checked"] and r["texts"] == T and r["fixed"] == [] and len(calls) == 1)
r = ic.proofread(T, reply_seq(RuntimeError("down")))
check("R3 Claude call fails: no exception, text unchanged, checked=False", r["checked"] is False and r["texts"] == T)
r = ic.proofread(T, reply_seq("non lo so"))
check("R4 unusable reply: text unchanged, checked=False (never treated as 'all correct')", r["checked"] is False and r["texts"] == T)
r = ic.proofread(T, reply_seq('{"errors": [{"wrong": "garantono", "fix": "garantiscono"}]}', '{"errors": [{"wrong": "comodità", "fix": "comodita"}]}'))
check("R5 an error still reported after the fix is returned in 'remaining'", r["remaining"] == [{"wrong": "comodità", "fix": "comodita"}] and r["fixed"], r)
big = '{"errors": [' + ",".join('{"wrong": "garantono", "fix": "x%d"}' % i for i in range(20)) + ']}'
r = ic.proofread(T, reply_seq(big))
check("R6 a reply with more than 8 errors is a confused checker: ignored", r["checked"] is False and r["texts"] == T)
check("F1 feedback lines name the wrong and the correct words", ic.feedback_lines([{"wrong": "garantono", "fix": "garantiscono"}]) == ['"garantono" is not correct Italian: write "garantiscono"'])
pr = ic.build_prompt(T)
check("S1 the prompt asks for language errors only (no style, no proper names, no numbers) and numbers the texts", "Do NOT list" in pr and "proper names" in pr and "1. Due camere" in pr and "2. Il giardino" in pr)
src = open("listing_scraper.py").read()
check("S2 all three narration paths call the ONE helper _proofread (blocks, per-scene script, single text)", src.count("_proofread(") == 4, src.count("_proofread("))

# ---- dictionary stage (2026-10-26, Patch AD): the dictionary finds the unknown words, Claude judges only those ----
KNOWN = {"due", "camere", "notte", "comodità", "abitativa", "il", "giardino", "è", "di", "60", "metri", "quadri", "garantiscono"}
def unk(words): return {w for w in words if w not in KNOWN}
calls.clear()
r = ic.proofread(T, reply_seq('{"errors": [{"wrong": "garantono", "fix": "garantiscono"}]}'), unknown_fn=unk)
check("D1 dictionary finds the typo, ONE call about that word, fixed; the re-check needs no call (nothing new to ask)", r["texts"][0].count("garantiscono") == 1 and r["remaining"] == [] and len(calls) == 1 and "garantono" in calls[0].split("TEXT:")[0], (r, len(calls)))
calls.clear()
r = ic.proofread(["Il giardino è di 60 metri quadri."], reply_seq(), unknown_fn=unk)
check("D2 no unknown word: NO Claude call at all, checked=True", r["checked"] and r["fixed"] == [] and calls == [])
calls.clear()
r = ic.proofread(["Il giardino è a Saba."], reply_seq('{"errors": []}'), context="Rione San Saba", unknown_fn=unk)
check("D3 words of the listing / address / agency (context) are never put to Claude", calls == [] and r["checked"])
calls.clear()
r = ic.proofread(["Il giardino è terrazzato."], reply_seq('{"errors": []}'), unknown_fn=unk)
check("D4 a word the dictionary lacks but Claude says is fine stays untouched (1 call, text identical)", r["texts"] == ["Il giardino è terrazzato."] and len(calls) == 1 and r["fixed"] == [])
r = ic.proofread(["Il giardino è terrazzato."], reply_seq('{"errors": [{"wrong": "giardino", "fix": "orto"}]}'), unknown_fn=unk)
check("D5 Claude naming a word that was NOT put to it (a known word) is ignored", r["texts"] == ["Il giardino è terrazzato."] and r["fixed"] == [])
r = ic.proofread(T, reply_seq(RuntimeError("down")), unknown_fn=unk)
check("D6 dictionary mode, Claude fails: text unchanged, checked=False", r["checked"] is False and r["texts"] == T)
def boom(words): raise RuntimeError("dictionary broke")
r = ic.proofread(T, reply_seq(), unknown_fn=boom)
check("D7 dictionary fails: no exception, text unchanged, checked=False", r["checked"] is False and r["texts"] == T)
calls.clear()
r = ic.proofread(["Due camere notte garantono comodità abitativa. Il giardino è terrazzato."], reply_seq('{"errors": [{"wrong": "garantono", "fix": "garantiscono"}]}', '{"errors": []}'), unknown_fn=unk)
check("D8 after a fix, the re-check asks only about words not already judged fine (here 'terrazzato' is not asked again)", len(calls) == 1 or "terrazzato" not in calls[-1].split("TEXT:")[0], calls)
check("D9 parse: a reply that reasons aloud and shows two JSON blocks counts by the LAST one (draft 7ff8ec4b Haiku reply)",
      ic.parse('```json\n{"errors": [{"wrong": "a b", "fix": "c"}]}\n```\nWait, let me reconsider.\n```json\n{"errors": []}\n```') == [])
check("D10 parse: a reasoning text with other braces before the answer still parses", ic.parse('ok {x} e poi {"errors": [{"wrong": "garantono", "fix": "garantiscono"}]}') == [{"wrong": "garantono", "fix": "garantiscono"}])
src2 = open("listing_scraper.py").read()
check("D11 the production helper passes the dictionary to italian_check", "unknown_fn=_italian_unknown_words()" in src2 and "pyspellchecker" in open("requirements.txt").read())
check("D12 the dictionary prompt forbids changing a correct word to another correct form ('contatta' must not become 'contattate')",
      "NOT an error" in ic.SUSPECT_PROMPT and "contatta" in ic.SUSPECT_PROMPT and "contattate" in ic.SUSPECT_PROMPT)
check("D13 a change of the last 1-2 letters is a choice of form, not a typo: ignored (contatta -> contatti / contattate)",
      ic.usable_errors([{"wrong": "contatta", "fix": "contatti"}, {"wrong": "contatta", "fix": "contattate"}], ["Contatta Gallo Immobiliare."]) == [])
check("D14 a real typo and a missing accent are still corrected", len(ic.usable_errors([{"wrong": "garantono", "fix": "garantiscono"}], T)) == 1
      and len(ic.usable_errors([{"wrong": "comodita", "fix": "comodità"}], ["Offre comodita abitativa."])) == 1
      and len(ic.usable_errors([{"wrong": "terazza", "fix": "terrazza"}], ["Una terazza ampia."])) == 1
      and len(ic.usable_errors([{"wrong": "luminosse", "fix": "luminose"}], ["Stanze luminosse."])) == 1)
print(f"\n{sum(res)}/{len(res)} PASS"); sys.exit(0 if all(res) else 1)
