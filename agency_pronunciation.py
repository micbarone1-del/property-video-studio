"""agency_pronunciation.py -- the ONE place that knows how an agency NAME is spoken and whether its pronunciation was validated (2026-11-19, Michele).
Pure functions, no I/O: tested without the server.

Rules (decided with Michele):
- A NEW partner agency starts with pronunciation_validated = False. Agencies created before this feature have no such key and count as validated.
- Until validated: no automatic release of that agency's videos (a manual release is always possible and is the operator's own check).
- The name is replaced in the spoken text whatever its case (THRINAKIE, Thrinakie, thrinakie). A name written ALL CAPS is never sent to the voice as
  it is (a voice may spell it like an acronym): without a stored pronunciation the proposal is the Capitalised name.
- 'Partial' name: when the name and the pronunciation end with the same words (THRINAKIE GROUP / Trinachie Group), the leading words alone
  (THRINAKIE) are replaced too.
- The replacement happens in voice_generation.apply_pronunciation_fixes, the single choke point of every TTS call, before the global word file."""
import re


def needs_validation(agency) -> bool:
    return bool(agency) and agency.get("pronunciation_validated") is False


def default_proposal(name: str) -> str:
    """The name with every ALL-CAPS word Capitalised: GIAL IMMOBILIARE -> Gial Immobiliare. Delegates to scene_script.spoken_name, the ONE
    implementation (it already does this for the narration prompts since 2026-11-13); nothing is reimplemented here."""
    import scene_script
    return scene_script.spoken_name(str(name or "").strip()) or ""


def effective(agency) -> str:
    """What the voice is told to say for this agency: the stored pronunciation, else the proposal."""
    pron = str((agency or {}).get("pronunciation") or "").strip()
    return pron or default_proposal((agency or {}).get("name") or "")


def _participates(agency) -> bool:
    """Legacy agencies (no validation key, no pronunciation) keep today's behaviour: no rule at all."""
    return bool(agency) and bool((agency.get("name") or "").strip()) and (
        "pronunciation_validated" in agency or bool(str(agency.get("pronunciation") or "").strip()))


def _pattern(tokens):
    return re.compile(r"(?<!\w)" + r"\s+".join(re.escape(t) for t in tokens) + r"(?!\w)", re.I)


def rules(agencies) -> list:
    """[(compiled regex, replacement)], longest pattern first, for the voice."""
    out = []
    for a in agencies or []:
        if not _participates(a):
            continue
        n_toks, p_toks = a["name"].split(), effective(a).split()
        if not n_toks or not p_toks:
            continue
        out.append((_pattern(n_toks), " ".join(p_toks)))
        n_pre, p_pre = list(n_toks), list(p_toks)
        while len(n_pre) > 1 and len(p_pre) > 1 and n_pre[-1].casefold() == p_pre[-1].casefold():
            n_pre.pop()
            p_pre.pop()
        if len(n_pre) < len(n_toks) and " ".join(n_pre) != " ".join(p_pre):
            out.append((_pattern(n_pre), " ".join(p_pre)))
    out.sort(key=lambda r: -len(r[0].pattern))
    return out


def apply(text: str, agencies) -> str:
    for rx, rep in rules(agencies):
        text = rx.sub(lambda m, r=rep: r, text)
    return text


def clean_pronunciation(raw) -> str:
    """What the operator typed, made safe: one line, plain text, no markup, at most 120 characters."""
    s = re.sub(r"[<>\r\n\t]+", " ", str(raw or ""))
    return re.sub(r"\s{2,}", " ", s).strip()[:120]
