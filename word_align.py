"""Word-level timing helpers for the anchor-driven timeline (2026-10-23, backlog 82, Patch J). Pure: no audio, no network.

We KNOW the text that was spoken; the speech recogniser (word_timing.py) only tells us WHEN each word was said. Its
spelling is not trusted (live test 2026-10-23: 'parquet' came back as 'parche', 'quadro' as 'quadri'), so the recognised
words are ALIGNED to the known text and only their times are used. A word the recogniser got wrong gets a time
interpolated between its neighbours, so a recognition mistake costs a fraction of a second, never a wrong scene.
"""
import difflib
import re
import unicodedata

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _fold(text: str) -> str:
    """lower-case, accents removed: 'perché' == 'perche'."""
    return "".join(c for c in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(c) != "Mn")


def tokens(text: str) -> list:
    """Words as the spoken comparison sees them. An apostrophe separates words ("l'appartamento" -> l, appartamento),
    as the recogniser does; punctuation is dropped; '1.680.000' -> 1, 680, 000 on both sides of the comparison."""
    return _TOKEN_RE.findall(_fold(text))


def find_phrase(text_tokens: list, phrase: str) -> list:
    """Start indexes (in text_tokens) where the phrase occurs as a run of whole tokens. [] when it does not."""
    p = tokens(phrase)
    if not p:
        return []
    return [i for i in range(len(text_tokens) - len(p) + 1) if text_tokens[i:i + len(p)] == p]


def _expand_recognised(recognised: list):
    """[(word, start, end)] -> parallel lists (tokens, starts, ends); a recognised word that is several tokens
    ('L'appartamento') shares its time between them by length."""
    toks, starts, ends = [], [], []
    for word, s, e in recognised or []:
        parts = tokens(word)
        if not parts:
            continue
        total = sum(len(p) for p in parts)
        t = float(s)
        for p in parts:
            dt = (float(e) - float(s)) * len(p) / total
            toks.append(p)
            starts.append(t)
            ends.append(t + dt)
            t += dt
    return toks, starts, ends


def align(text_tokens: list, recognised: list) -> dict:
    """Times for every token of the known text.
    Returns {"times": [(start, end)] one per text token, "matched": int, "coverage": matched / len(text_tokens),
    "end": time the last recognised word ends}. Unmatched tokens are interpolated between matched neighbours
    (proportionally to their length); coverage tells how much of the text was really found in the audio."""
    rec_t, rec_s, rec_e = _expand_recognised(recognised)
    n = len(text_tokens)
    if n == 0 or not rec_t:
        return {"times": [], "matched": 0, "coverage": 0.0, "end": 0.0}
    sm = difflib.SequenceMatcher(None, text_tokens, rec_t, autojunk=False)
    times = [None] * n
    matched = 0
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            times[a + k] = (rec_s[b + k], rec_e[b + k])
            matched += 1
    end_all = rec_e[-1]
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else 0.0
        right = times[j][0] if j < n else end_all
        if right < left:
            right = left
        total = sum(len(text_tokens[k]) for k in range(i, j))
        t = left
        for k in range(i, j):
            dt = (right - left) * len(text_tokens[k]) / total
            times[k] = (t, t + dt)
            t += dt
        i = j
    return {"times": times, "matched": matched, "coverage": matched / n, "end": end_all}
