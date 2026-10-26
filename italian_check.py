"""Italian language check for the narration (2026-10-26, Michele: draft 7ff8ec4b said "garantono" instead of "garantiscono").

ONE implementation for every narration path (blocks, per-scene script, single text). Patch AD: an Italian dictionary (pyspellchecker)
finds the words it does not know and Claude judges ONLY those (reading the whole text as a proofreader missed "garantono" with both Haiku 4.5
and Sonnet 5.5, measured 2026-10-26); the errors it reports are applied as plain word replacements. Without the dictionary installed it falls
back to proofreading the whole text. It never raises and never blocks a narration: if the call fails or answers badly the text goes on
unchanged (checked=False, recorded in the log). Limits: a typo that is itself a real word, and grammar (agreement, a missing verb), are not found.

    proofread(texts, reply_fn, context="", unknown_fn=None) -> {"texts": [...], "fixed": [{"wrong","fix"}], "remaining": [{"wrong","fix"}], "checked": bool}

reply_fn(prompt) -> str is the project's Claude text call (listing_scraper._claude_text_reply, which also counts the cost).
"""
import json
import re

MAX_FIX_WORDS = 3          # a correction longer than this is not a spelling/grammar fix: ignored
MAX_ERRORS = 8             # more than this means the checker is confused: ignored, not applied

PROMPT = """You are a meticulous proofreader of Italian. Below is the Italian voiceover of a real estate video (one line per text).
List ONLY real language errors: misspelled or non-existent words, a wrong verb form (for example "finono" instead of "finiscono"), wrong gender or number agreement, a wrong or missing article or preposition, a word order no native speaker would use.
Do NOT list: style or tone, punctuation, proper names (people, places, streets, agencies), numbers, abbreviations, or anything that is merely unusual but correct. If everything is correct Italian, return an empty list.
Reply with ONLY this JSON object, nothing else:
{{"errors": [{{"wrong": "<the exact 1-3 words as written in the text>", "fix": "<the same words, corrected>"}}]}}

TEXT:
{text}"""


def build_prompt(texts: list) -> str:
    return PROMPT.format(text="\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts)))


def parse(raw) -> list | None:
    """The list of {"wrong","fix"} in the LAST {"errors": [...]} object of the reply (a reply that reasons aloud and shows several JSON
    blocks counts by its last one), [] when it reports none, None when the reply is not usable."""
    if not raw:
        return None
    raw, dec, i, errs = str(raw), json.JSONDecoder(), 0, None
    while True:
        i = raw.find("{", i)
        if i < 0:
            break
        try:
            obj, end = dec.raw_decode(raw[i:])
            if isinstance(obj, dict) and isinstance(obj.get("errors"), list):
                errs = obj["errors"]
            i += end
        except Exception:
            i += 1
    if errs is None:
        return None
    out = []
    for e in errs:
        if isinstance(e, dict) and isinstance(e.get("wrong"), str) and isinstance(e.get("fix"), str):
            out.append({"wrong": e["wrong"].strip(), "fix": e["fix"].strip()})
    return out


def _word_rx(wrong: str):
    return re.compile(r"(?<!\w)" + re.escape(wrong) + r"(?!\w)", re.IGNORECASE)


def _inflection_only(wrong: str, fix: str) -> bool:
    """True when the 'fix' only swaps the final vowel of a word ("contatta" -> "contatti") or adds / removes a 2-3 letter ending
    ("contatta" -> "contattate"): that is a choice of form (tu / voi / Lei, singular / plural), not a typo, and both forms are correct
    Italian - measured 2026-10-26: the model rewrote "contatta" in a correct closing even when told not to. Real typos are never like
    that ("garantono" -> "garantiscono", "luminosse" -> "luminose", "terraza" -> "terrazza"); a missing accent ("comodita" -> "comodità")
    stays allowed."""
    import unicodedata
    def plain(x):
        return "".join(c for c in unicodedata.normalize("NFD", x.lower()) if unicodedata.category(c) != "Mn")
    w, f = wrong.lower(), fix.lower()
    if " " in w or " " in f or plain(w) == plain(f):
        return False
    common = 0
    for x, y in zip(w, f):
        if x != y:
            break
        common += 1
    tw, tf = w[common:], f[common:]
    if len(tw) == 1 and len(tf) == 1 and tw in "aeiou" and tf in "aeiou":
        return True
    return (tw == "" and 2 <= len(tf) <= 3) or (tf == "" and 2 <= len(tw) <= 3)


def usable_errors(errors: list, texts: list, context: str = "", allowed=None) -> list:
    """Keeps only the reports that can be applied safely: the wrong words really are in the text, the fix is different and short,
    and the words are not in the listing / address / agency name (proper names and the listing's own wording are never 'corrected')."""
    joined = " ".join(texts)
    ctx = (context or "").lower()
    out, seen = [], set()
    for e in errors or []:
        w, f = e["wrong"], e["fix"]
        if not w or not f or w.lower() == f.lower() or len(f.split()) > MAX_FIX_WORDS or len(w.split()) > MAX_FIX_WORDS:
            continue
        if not _word_rx(w).search(joined):
            continue
        if w.lower() in ctx:
            continue
        if allowed is not None and w.lower() not in allowed:
            continue
        if _inflection_only(w, f):
            continue
        if w.lower() in seen:
            continue
        seen.add(w.lower())
        out.append({"wrong": w, "fix": f})
    return out


def apply(texts: list, errors: list) -> list:
    """Whole-word replacements (a capital first letter is kept)."""
    out = []
    for t in texts:
        for e in errors:
            def _sub(m, f=e["fix"]):
                return (f[:1].upper() + f[1:]) if m.group(0)[:1].isupper() else f
            t = _word_rx(e["wrong"]).sub(_sub, t)
        out.append(t)
    return out


SUSPECT_PROMPT = """You are a meticulous proofreader of Italian. Below is the Italian voiceover of a real estate video, and a list of words from it that our dictionary does not know.
Many of them are correct (rare words, inflected forms, proper names, technical terms). Report ONLY the words that are misspelled, mistyped or not real Italian words (for example "garantono" instead of "garantiscono"), each with the corrected word: a real Italian word that fits the sentence.
A word that is correct Italian is NOT an error, even if another form or wording would also fit or sound nicer: for example "contatta" (imperative of contattare, "you contact") is correct, do not change it to "contattate" or anything else; the same for tu / voi / Lei forms, synonyms, plural or singular that agree with the sentence.\nDo not report anything else, and no word that is not in the list. If every listed word is fine, return an empty list.
Reply with ONLY this JSON object, nothing else, no explanation:
{{"errors": [{{"wrong": "<the word exactly as written>", "fix": "<the corrected word>"}}]}}

WORDS NOT IN THE DICTIONARY: {words}

TEXT:
{text}"""

MAX_SUSPECTS = 12          # more unknown words than this: the dictionary is not fit for this text, only the first ones are asked about


def suspects(texts: list, context: str, unknown_fn, skip=()) -> list:
    """Words of the texts that the dictionary (unknown_fn(list of lowercase words) -> set of the unknown ones) does not know, minus the
    words of the listing / address / agency name (context), one-letter words and the words already judged fine (skip)."""
    ctx = set(re.findall(r"[^\W\d_]+", (context or "").lower().replace("'", " ")))
    words = []
    for t in texts:
        for w in re.findall(r"[^\W\d_]+", t.lower().replace("'", " ")):
            if len(w) >= 3 and w not in ctx and w not in skip and w not in words:
                words.append(w)
    return [w for w in words if w in set(unknown_fn(words))][:MAX_SUSPECTS]


def _find(texts: list, reply_fn, context: str, unknown_fn=None, skip=()):
    """(usable errors, checked, asked). checked=False when the call failed or the reply was not usable.
    With unknown_fn only the words the dictionary does not know are put to Claude (and no call at all when there are none): asking a model
    to find a typo in a fluent text does not work (it reads "garantono" as "garantiscono"); asking about one named word does.
    Without unknown_fn the whole text is proofread (fallback when no dictionary is available)."""
    asked = []
    if unknown_fn is None:
        prompt, allowed = build_prompt(texts), None
    else:
        try:
            asked = suspects(texts, context, unknown_fn, skip)
        except Exception:
            return [], False, []
        if not asked:
            return [], True, []
        prompt = SUSPECT_PROMPT.format(words=", ".join(asked), text="\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts)))
        allowed = set(asked)
    try:
        raw = reply_fn(prompt)
    except Exception:
        return [], False, asked
    errs = parse(raw)
    if errs is None or len(errs) > MAX_ERRORS:
        return [], False, asked
    return usable_errors(errs, texts, context, allowed), True, asked


def proofread(texts: list, reply_fn, context: str = "", unknown_fn=None) -> dict:
    texts = list(texts)
    errs, checked, asked = _find(texts, reply_fn, context, unknown_fn)
    if not checked or not errs:
        return {"texts": texts, "fixed": [], "remaining": [], "checked": checked}
    fixed_texts = apply(texts, errs)
    cleared = {w for w in asked if w not in {e["wrong"].lower() for e in errs}}   # words Claude judged fine: not asked about again
    again, checked2, _ = _find(fixed_texts, reply_fn, context, unknown_fn, cleared)
    return {"texts": fixed_texts, "fixed": errs, "remaining": again if checked2 else [], "checked": True}


def feedback_lines(errors: list) -> list:
    return [f'"{e["wrong"]}" is not correct Italian: write "{e["fix"]}"' for e in errors]
