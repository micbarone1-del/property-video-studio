"""narration_log.py - phase 2 of the learning loop (2026-11-25): remembers WHY each narration attempt was rejected.
Additive and passive: a context-local list; note() never raises and never changes a narration; begin()/end() wrap the one entry point
(listing_scraper.generate_narration_and_derive_scenes). The list ends up in the result dict as "narration_rejections" and in job_meta.
No new registry file: job_meta is the store, learning_loop.py reads it."""
import contextvars
import re

_CUR = contextvars.ContextVar("narration_rejections", default=None)
MAX_ITEMS = 40


def begin():
    try:
        return _CUR.set([])
    except Exception:
        return None


def code_of(problem) -> str:
    """Stable rule code from a free-text problem: digits and quoted text removed, first 60 chars."""
    try:
        s = re.sub(r"\d+", "#", str(problem))
        s = re.sub(r"[\"'«»“”][^\"'«»“”]*[\"'«»“”]", "'..'", s)
        return s.strip()[:60]
    except Exception:
        return "?"


def note(stage, attempt, problems) -> None:
    try:
        lst = _CUR.get()
        if lst is None or len(lst) >= MAX_ITEMS:
            return
        if isinstance(problems, str):
            problems = [problems]
        lst.append({"stage": str(stage), "attempt": int(attempt), "codes": [code_of(p) for p in (problems or [])][:8]})
    except Exception:
        pass


def end(token):
    """Returns the collected list (copy) and resets the context. Never raises."""
    try:
        lst = list(_CUR.get() or [])
        if token is not None:
            _CUR.reset(token)
        return lst
    except Exception:
        return []
