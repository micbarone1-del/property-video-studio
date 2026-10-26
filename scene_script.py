"""
scene_script.py
---------------
Per-scene narration script for the STANDARD URL/Relinx video (Patch B, 2026-10-22).

Decision (Michele, 2026-10-22): the standard video is 6 scenes x 5 s. Instead of one free text that is only
re-timed, Claude writes ONE short sentence per scene, in scene order, knowing which room each scene shows:

  1  opening      agency + sale/rent + property type + zone           (about 12-13 words)
  2  general      general facts of the property (size, levels, state) (about 12-13 words; NOT a room description)
  3-5 rooms       one sentence about the room shown, a detail only if the listing text says it
  6  closing      last scene + invitation to contact the agency by name

The voice stays ONE continuous track: the sentences are joined and go through the same shared narration code
(narration.synthesize_sentences / assemble_narration / plan_sentence_sync) as before, which starts each
sentence on its scene cut. The price and floor references are never spoken.

This module is pure (no network, no audio): prompt building, parsing and the FACT CHECK. Every number and
every risky feature word in a sentence must appear in the listing text, otherwise the sentence is rejected
(see validate()). It is a heuristic safety net, not a proof: a person still listens to the first real jobs.
"""
import json
import re

SCENES = 6
MAX_WORDS = 14            # hard ceiling for scenes 1-5 (about 5 s of speech); the target is 12-13
MAX_WORDS_LAST = 17       # scene 6 may run into the trailing blank (narration.MAX_OVERFLOW_SECS absorbs up to 2 s)
MIN_WORDS = 4
SOFT_WORDS = 2            # 2026-10-22: words are only a proxy for seconds (live test: the model wrote 15-16 words
                          # twice and the whole script was discarded). Up to this many words over the ceiling are
                          # accepted here; the REAL check is the measured audio (spill_problems + one tighten pass).
SPILL_TOLERANCE_SECS = 0.8   # a sentence that ends more than this after its scene ends gets shortened
WORDS_PER_SEC = 2.4

SENTENCE_ROLES = ["opening", "general", "room", "room", "room", "closing"]

_NUMBER_WORDS = {
    "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
    "undici": 11, "dodici": 12, "venti": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50,
    "cento": 100, "mille": 1000,
}

# A feature word in a sentence is only allowed when the same stem is in the listing text.
_FEATURE_STEMS = [
    "piscin", "giardin", "terrazz", "balcon", "box", "garage", "camin", "ascensor", "cantin", "tavern",
    "mansard", "domotic", "condizionat", "riscaldament", "vista", "mare", "lago", "parco", "portier",
    "idromassagg", "jacuzzi", "sauna", "palestr", "cancell", "allarm", "videosorveglian", "fotovoltaic",
    "parquet", "marmo", "travertin", "soppalc", "lavander", "dependance", "anness", "uliv", "pergol",
    "portic", "veranda", "doppi servizi", "arredat", "ristrutturat", "nuov",
]

# Promotional adjectives: only allowed when the listing text itself uses the same stem.
_PROMO_STEMS = [
    "prestigios", "esclusiv", "meraviglios", "splendid", "lussuos", "incantevol", "mozzafiato", "unic",
    "straordinari", "eccezional", "elegant", "raffinat", "pregiat", "magnific", "favolos", "sontuos",
]

# Floors are never named in the standard video (Michele, 2026-10-22): a photo's floor is not known.
_FLOOR_RE = re.compile(
    r"\b(piano terra|primo piano|secondo piano|terzo piano|ultimo piano|piano rialzato|piano superiore|"
    r"piano inferiore|piano interrato|seminterrato|interrato|al piano|del piano|sul piano)\b", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _number_tokens(text: str) -> set:
    """'650', '1.680.000', '2,5' -> {'650', '1680000', '25'} (separators removed on both sides of the comparison)."""
    out = set()
    for m in re.findall(r"\d+(?:[.,]\d+)*", text or ""):
        out.add(re.sub(r"[.,]", "", m))
    return out


def _price_tokens(description: str) -> set:
    """Numbers the listing itself ties to money ('1.680.000 euro', '€ 1.200', '850 € al mese'). The Relinx workflow does
    not pass the price separately, so the listing text is the only place to learn which numbers are prices."""
    out = set()
    for m in re.finditer(r"(?:€|euro)\s*(\d[\d.,]*)|(\d[\d.,]*)\s*(?:€|euro)", description or "", re.I):
        raw = m.group(1) or m.group(2)
        out.add(re.sub(r"[.,]", "", raw))
    return out


def _has_stem(text: str, stem: str) -> bool:
    """stem at the START of a word ('giardin' matches 'giardino', not 'ingiardinare'-like accidents inside words)."""
    return re.search(r"(?<![a-zàèéìòù])" + re.escape(stem), text) is not None


def words(sentence: str) -> list:
    return [w for w in re.split(r"\s+", (sentence or "").strip()) if w]


# 2026-10-25: one wording for the three prompts below (it was triplicated). Square metres are spoken 'metri quadri'
# (the voice spells 'mq' letter by letter and stops after the abbreviation); voice_generation.spoken_units is the safety net.
NUMBERS_RULE = "- Numbers: copy them as the listing writes them, number first (e.g. '650 metri quadri'). Always write square metres in full as 'metri quadri': never 'mq', never 'm2', never 'metri quadrati'."
VERB_RULE = ("- Every sentence needs a conjugated verb. A noun phrase alone is NOT a sentence: never 'Il giardino terrazzato di circa 60 metri quadri.' "
             "but 'Il giardino terrazzato misura circa 60 metri quadri.' (or 'Il giardino è di circa 60 metri quadri'). Keep the short sentences short, but with a verb.")


def build_prompt(description: str, address: str, agency_name: str, labels: list) -> str:
    """labels: the Italian name of the room each of the 6 scenes shows, in video order."""
    agency = agency_name or "(agency name not available: say 'l'agenzia')"
    scene_lines = []
    for i, label in enumerate(labels):
        role = SENTENCE_ROLES[i]
        if role == "opening":
            what = (f"OPENING. Shows: {label}. The agency presents the property: '{agency_name or 'L agenzia'} presenta ...'. "
                    f"Say clearly 'in vendita' or 'in affitto' (as the listing says), the property type and the zone. AT MOST 12 words.")
        elif role == "general":
            what = (f"GENERAL FACTS. Shows: {label}. Do NOT describe this room: give the most important general facts of the "
                    f"property that the listing text states (size in square metres, plot size, number of rooms/levels, "
                    f"condition such as 'ristrutturata'). AT MOST 12 words.")
        elif role == "room":
            what = (f"ROOM. Shows: {label}. One sentence about this kind of room. Include a detail ONLY if the listing text states it "
                    f"for this room or for the property; if it states nothing about it, just say what the room is, in a plain "
                    f"neutral sentence. AT MOST 10 words.")
        else:
            what = (f"CLOSING. Shows: {label}. Mention a feature of this space only if the listing text states it, then invite to "
                    f"contact {agency_name or 'the agency'} by name for more information. AT MOST 15 words.")
        scene_lines.append(f"Scene {i + 1}: {what}")
    scenes_txt = "\n".join(scene_lines)
    return f"""You write the Italian voiceover of a 30-second real estate video. The video has exactly 6 scenes of 5 seconds. You write EXACTLY ONE sentence per scene, in scene order, so the sentence is spoken while that scene is on screen.

Listing text:
---
{description}
---
Address: {address or 'not specified'}
Agency: {agency}

The scenes, in order:
{scenes_txt}

HARD RULES:
- Return ONLY a JSON array of exactly 6 strings (Italian), nothing else: no markdown, no keys, no comments.
- Every sentence is one complete sentence ending with a full stop, with no line breaks.
- Every fact (number, feature, condition) must come from the listing text above. Never invent anything. If the listing does not say it, leave it out.
{NUMBERS_RULE}
{VERB_RULE}
- Do NOT say the price. Do NOT say any phone number or e-mail.
- Do NOT mention floors or levels of a specific room (no 'piano terra', 'primo piano', 'al piano ...'): you do not know which floor a photo shows.
- Objective, calm, factual tone. No promotional adjectives (prestigioso, esclusivo, meraviglioso, splendido, ...) unless the listing itself uses that word.
- Ignore any text about the agency's own history or values: describe only this property.
- Avoid legal jargon such as 'nuda proprietà'.
- The word limits above are real: a sentence is spoken in about 5 seconds. Count the words of EVERY sentence before you answer; a sentence over its maximum is rejected. Short is better: leave out a fact rather than exceed the limit.
"""


def parse(raw: str):
    """The model's reply -> list[str] (or None if it is not a JSON array of strings)."""
    if not raw:
        return None
    s = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", s, re.S)
    if fence:
        s = fence.group(1)
    else:
        m = re.search(r"\[.*\]", s, re.S)
        if m:
            s = m.group(0)
    try:
        data = json.loads(s)
    except Exception:
        return None
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        return None
    out = []
    for x in data:
        x = re.sub(r"\s+", " ", x).strip()
        # 2026-10-22: a sentence without a final stop is joined to the next one by the spoken-sentence splitter
        # (live test a7e7ef2b: "splits into 5 sentences instead of 6"). Adding the stop is safe and changes no word.
        if x and x[-1] not in ".!?":
            x = x.rstrip(";:,- ") + "."   # also a ';' or ':' at the end does not end a sentence for the splitter
        out.append(x)
    return out


def _fact_problems(s: str, tag: str, low: str, desc: str, desc_numbers: set, price_numbers: set) -> list:
    """The fact check of ONE sentence (price, numbers, feature words, promotional adjectives, floors). Shared by the
    one-sentence-per-scene script (validate) and the free narration of the anchor-driven timeline
    (validate_free_text): ONE implementation, not two copies (architecture discipline, 2026-10-23)."""
    problems = []
    if "€" in s or re.search(r"\beuro\b", low):
        problems.append(f"{tag}: mentions the price")
    for tok in _number_tokens(s):
        if price_numbers and tok in price_numbers and tok not in (desc_numbers - price_numbers):
            problems.append(f"{tag}: says the price ({tok})")
        elif len(tok) >= 8:
            problems.append(f"{tag}: looks like a phone number ({tok})")
        elif tok not in desc_numbers:
            problems.append(f"{tag}: number {tok} is not in the listing text")
    for w in re.findall(r"[a-zàèéìòù]+", low):
        if w in _NUMBER_WORDS:
            val = str(_NUMBER_WORDS[w])
            if not _has_stem(desc, w) and val not in desc_numbers:
                problems.append(f"{tag}: number word '{w}' is not in the listing text")
    for stem in _FEATURE_STEMS:
        if _has_stem(low, stem) and not _has_stem(desc, stem):
            problems.append(f"{tag}: feature '{stem}...' is not in the listing text")
    for stem in _PROMO_STEMS:
        if _has_stem(low, stem) and not _has_stem(desc, stem):
            problems.append(f"{tag}: promotional adjective '{stem}...' is not in the listing text")
    if _FLOOR_RE.search(s):
        problems.append(f"{tag}: names a floor")
    return problems


def validate(sentences: list, description: str, agency_name: str = None, price: str = None, split_fn=None) -> list:
    """Returns a list of problems (empty list = script accepted). Deterministic, no network."""
    problems = []
    if not isinstance(sentences, list) or len(sentences) != SCENES:
        return [f"expected exactly {SCENES} sentences, got {len(sentences) if isinstance(sentences, list) else 'none'}"]
    desc = _norm(description)
    desc_numbers = _number_tokens(description)
    price_numbers = (_number_tokens(price) if price else set()) | _price_tokens(description)
    agency_n = re.sub(r"[^a-z0-9àèéìòù ]", "", _norm(agency_name)) if agency_name else ""

    for i, s in enumerate(sentences):
        tag = f"scene {i + 1}"
        low = _norm(s)
        n_words = len(words(s))
        limit = MAX_WORDS_LAST if i == SCENES - 1 else MAX_WORDS
        if not s or n_words < MIN_WORDS:
            problems.append(f"{tag}: too short or empty")
            continue
        if n_words > limit + SOFT_WORDS:
            problems.append(f"{tag}: {n_words} words, maximum {limit}")
        if "\n" in s or not s.endswith("."):
            problems.append(f"{tag}: must be one sentence ending with a full stop")
        if s.count(".") > 1 and not re.search(r"\d\.\d", s):
            problems.append(f"{tag}: contains more than one sentence")
        problems.extend(_fact_problems(s, tag, low, desc, desc_numbers, price_numbers))
        if i == 0:
            says_sale = "vendita" in low
            says_rent = "affitto" in low
            if not (says_sale or says_rent):
                problems.append("scene 1: must say 'in vendita' or 'in affitto'")
            if says_sale and not any(k in desc for k in ("vendita", "vendesi", "vendiamo", "vendere")):
                problems.append("scene 1: says 'in vendita' but the listing text does not")
            if says_rent and not any(k in desc for k in ("affitto", "affittasi", "locazione", "locare")):
                problems.append("scene 1: says 'in affitto' but the listing text does not")
        if agency_n and i in (0, SCENES - 1) and agency_n not in re.sub(r"[^a-z0-9àèéìòù ]", "", low):
            problems.append(f"{tag}: must name the agency ({agency_name})")

    if split_fn is not None and not problems:
        # name the exact boundary the splitter cannot see (splits only on . ! ? followed by a capital letter)
        for i, sent in enumerate(sentences):
            if i > 0 and not re.match(r"[A-ZÀ-Ü]", sent):
                problems.append(f"scene {i + 1}: must start with a capital letter (not a digit or lowercase): write numbers inside the sentence, not at its start")
        if problems:
            return problems
        joined = " ".join(sentences)
        parts = split_fn(joined)
        if len(parts) != SCENES:
            problems.append(f"the text splits into {len(parts)} sentences instead of {SCENES} when it is spoken")
    return problems


def spill_problems(sync: dict, scene_count: int = SCENES) -> list:
    """From the measured sync plan (narration.plan_sentence_sync): which sentences are too long for their scene.
    Returns [(sentence_index, spoken_secs_over_the_scene)], scenes 1-5 only: the last sentence is allowed to run
    into the trailing blank (the existing overflow rule judges that one)."""
    bad = []
    for r in (sync or {}).get("rows", []):
        if r["index"] < scene_count - 1 and r.get("spill_secs", 0) > SPILL_TOLERANCE_SECS:
            bad.append((r["index"], r["spill_secs"]))
    return bad


def build_tighten_prompt(sentences: list, bad: list, description: str, agency_name: str = None) -> str:
    lines = []
    for idx, over in bad:
        target = max(6, len(words(sentences[idx])) - max(2, int(round(over * WORDS_PER_SEC)) + 1))
        lines.append(f"- sentence {idx + 1} is spoken about {over:.1f} s too long: rewrite it with at most {target} words, same meaning")
    return f"""Below are 6 Italian voiceover sentences, one per 5-second scene of a video. Some are too long to be spoken in their scene:
{chr(10).join(lines)}

MUST-KEEP words (live test c75f022c: a shortened sentence 1 lost 'in vendita' and the whole rewrite was thrown away): if you rewrite sentence 1 it must still say 'in vendita' or 'in affitto' exactly as the current sentence does, and name the agency{(' (' + agency_name + ')') if agency_name else ''}; if you rewrite sentence 6 it must still name the agency{(' (' + agency_name + ')') if agency_name else ''} and invite to contact it. Shorten by dropping details (condition adjectives, secondary facts), never these words.
Keep every OTHER sentence exactly unchanged. Keep every fact only if it is in the listing text. Do not add facts, do not say the price, do not name floors.
Return ONLY the JSON array of the 6 strings, nothing else.

Current sentences:
{json.dumps(sentences, ensure_ascii=False)}

Listing text:
---
{description}
---
"""


# ── Free narration with room anchors (2026-10-23, backlog 82, Patch J) ───────────────────────────────────────
# Michele's refinement: the requirement is not one sentence per scene, but that when the voice NAMES a room that
# room is on screen. So the text is a natural narration (about 56-66 words) and Claude
# also says WHICH phrase names the room of which scene. The time of that phrase is measured on the real audio
# (word_timing / word_align) and pins the scene's picture (scene_timing.plan_from_anchors). A room need not be named.

FREE_MIN_WORDS = 45
FREE_MAX_WORDS = 72           # 2026-10-23 (Patch K): was 95; a 90+ word text is ~40 s of voice and cannot fit 6 clips
PROMPT_WORDS = "56-66"        # what the prompt asks for (about 28 s of voice at the ~2.3 words/s measured on the single-text path)
TARGET_SPEECH_SECS = 28       # duration requirement written in the prompt
MAX_SPEECH_SECS = 32          # never more than this (6 clips at 0.8x last at most ~35 s with the cross-fades)
OPENING_MAX_WORDS = 13        # sentence 1 is spoken over scene 1 (about 5-6 s)
ROOM_SPACING_WORDS = 11       # about one new room every 11 words (~5 s of voice)
MAX_ANCHORS = 3               # 2026-10-23 (Patch O): 30 s cannot name every room: 2-3 highlights, the other scenes simply fill the time between them
ESTIMATE_WORDS_PER_SEC = 2.05 # 2026-10-23 (Patch N): measured 2.09 words/s on the draft 6cb22349 (2.14 on the first drafts); 2.2 was optimistic
ESTIMATE_TOLERANCE_SECS = 0.5 # Patch N: was 1.0, which let through a text that the real voice then missed by 0.95 s and 1.32 s
ESTIMATE_PREFIX = "estimated timing:"   # every message of estimate_timing_problems starts with this (the orchestrator tells them apart)


def build_anchored_prompt(description: str, address: str, agency_name: str, labels: list) -> str:
    """labels: the Italian name of what each of the 6 scenes shows, in video order."""
    agency = agency_name or "(agency name not available: say 'l'agenzia')"
    scene_lines = "\n".join(f"Scene {i + 1}: {label}" for i, label in enumerate(labels))
    return f"""You write the Italian voiceover of a 30-second real estate video. The video shows 6 scenes of about 5 seconds, in this order:
{scene_lines}

The voice is ONE continuous narration (natural flowing Italian, 4 to 7 short sentences). DURATION REQUIREMENT: spoken aloud it must last about {TARGET_SPEECH_SECS} seconds and NEVER more than {MAX_SPEECH_SECS} seconds. The voice speaks about 2.3 words per second, so the whole text must be {PROMPT_WORDS} words; a text of more than {FREE_MAX_WORDS} words is rejected automatically. Count your words before answering.

Listing text:
---
{description}
---
Address: {address or 'not specified'}
Agency: {agency}

STRUCTURE (ONE natural flowing narration, not a list of sentences about rooms):
- Open with the agency presenting the property ("{agency_name or "L'agenzia"} presenta ..."), saying clearly "in vendita" or "in affitto" (as the listing says), the property type and the zone. KEEP IT SHORT, at most {OPENING_MAX_WORDS} words: it is spoken over scene 1, which lasts only about 5 seconds. No size and no rooms in the opening.
- WHERE a highlight must be named: each scene lasts about 5 seconds (about 10 words), so the room of scene 2 is named around word 10 of the whole text, scene 3 around word 19, scene 4 around word 29, scene 5 around word 38, scene 6 around word 48 (give or take 4 words). A highlight named far from its place is rejected automatically, so write the sentences before it with that length in mind.
- Then continue as one natural flow with the most important general facts and the details the listing states. There is NO time to name every room: choose 2 or 3 HIGHLIGHTS among the rooms of scenes 2 to 6 (never more than {MAX_ANCHORS}): the ones with the most worth saying (special features first, for example the garden, a terrace, a particular living room). The rooms you do not name are simply not named: their pictures fill the time between the named ones.
- Name the highlights in the ORDER of the scenes. After naming a highlight, say something about it (a real fact from the listing) for about 12 to 20 words BEFORE the next highlight or the invitation: two highlights must be at least 12 words apart. Never "la cucina, seguita da due camere da letto". (The text is rejected automatically when a highlight is named too late or two are too close together.)
- Objective positive adjectives are welcome (for example luminoso, ampio, funzionale, curato, silenzioso, panoramico) when the listing text supports them: they make the description less bare. Never invent a quality.
- Last, a short invitation (at most 7 words) to contact {agency_name or 'the agency'} by name for more information. The LAST room you name (usually the garden or outdoor spaces, scene 6) must be named early enough that at most about 12 words follow it, the invitation included: so it is named in the second-to-last sentence or at the start of the last one, never followed by a long list.
- Do not name a room that comes EARLIER in the order after you have named a later one, and do not name a room twice (do not say "tre camere" in the opening if the bedrooms are a later scene: say it where they are shown).

HARD RULES:
- Return ONLY a JSON object, nothing else: {{"text": "<the whole Italian narration>", "anchors": [{{"scene": 3, "phrase": "la cucina"}}, ...]}}
- "anchors": one entry for each room (scene 2 to 6) that the text names. "phrase" is the 1 to 3 words that name it, copied EXACTLY as they appear in "text", and it must appear only once in "text". Use an empty list if you name no room. Scene 1 never has an anchor.
- Every fact (number, feature, condition) must come from the listing text above. Never invent anything. If the listing does not say it, leave it out.
{NUMBERS_RULE}
{VERB_RULE}
- Do NOT say the price. Do NOT say any phone number or e-mail.
- Do NOT mention floors or levels of a specific room (no 'piano terra', 'primo piano'): you do not know which floor a photo shows.
- Objective, calm, factual tone. Do NOT use hyperbolic or luxury adjectives (prestigioso, esclusivo, meraviglioso, splendido, lussuoso, incantevole, mozzafiato, straordinario, eccezionale, favoloso, magnifico, sontuoso, and also elegante, raffinato, pregiato) in ANY form (masculine, feminine, plural: splendido, splendida, splendidi, splendide) unless the listing itself uses that word. Plain objective adjectives (luminoso, ampio, funzionale, curato...) are fine when the listing supports them.
- Ignore any text about the agency's own history or values: describe only this property.
- Avoid legal jargon such as 'nuda proprietà'.
"""


def parse_anchored(raw: str):
    """The model's reply -> (text, anchors) or None. anchors = [{"scene": int (1-based), "phrase": str}]."""
    if not raw:
        return None
    s = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.S)
    if fence:
        s = fence.group(1)
    else:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            s = m.group(0)
    try:
        data = json.loads(s)
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        return None
    text = re.sub(r"\s+", " ", data["text"]).strip()
    if text and text[-1] not in ".!?":
        text = text.rstrip(";:,- ") + "."
    anchors = data.get("anchors", [])
    if not isinstance(anchors, list):
        return None
    out = []
    for a in anchors:
        if not isinstance(a, dict) or not isinstance(a.get("scene"), int) or not isinstance(a.get("phrase"), str):
            return None
        out.append({"scene": a["scene"], "phrase": re.sub(r"\s+", " ", a["phrase"]).strip()})
    return text, out


def estimate_timing_problems(text: str, anchors: list, labels: list = None, scenes: int = SCENES,
                             wps: float = ESTIMATE_WORDS_PER_SEC, tolerance: float = ESTIMATE_TOLERANCE_SECS) -> list:
    """Patch L (2026-10-23): checks WHERE the rooms are named BEFORE any voice is paid for. The time of each named room
    is estimated from its word position (position / wps) and the SAME solver that later runs on the real audio
    (scene_timing.plan_from_anchors, so no second copy of the speed/cut constants) says whether the clips fit.
    Only clips more than `tolerance` seconds outside the limits are reported (the estimate is not exact); the real
    check on the measured audio stays the last word. Returns problem strings with word counts the model can act on."""
    import word_align as wa
    import scene_timing as st
    tk = wa.tokens(text)
    if not tk or wps <= 0:
        return []
    times = [None] * scenes
    for a in anchors or []:
        sc = a.get("scene")
        if not isinstance(sc, int) or sc < 2 or sc > scenes:
            continue
        hits = wa.find_phrase(tk, a.get("phrase", ""))
        if len(hits) == 1:
            times[sc - 1] = hits[0] / wps
    plan = st.plan_from_anchors(times, len(tk) / wps, [st.DEFAULT_SRC_SECS] * scenes)
    out = []
    for p in plan["problems"]:
        if p["seconds_over"] <= tolerance:
            continue
        i = p["clip"]
        name = labels[i] if labels and i < len(labels) else f"scene {i + 1}"
        lo, hi = p["allowed_visible"]
        w = max(1, int(round(p["seconds_over"] * wps)))
        last_pos = None
        if i == scenes - 1:
            for a in anchors or []:
                if a.get("scene") == scenes:
                    h = wa.find_phrase(tk, a.get("phrase", ""))
                    last_pos = h[0] if len(h) == 1 else None
        if p["kind"] == "too_slow" and last_pos is not None:
            allowed = max(1, int((hi - st.LEAD_BEFORE_WORD - st.END_TAIL_SECS) * wps))
            msg = (f"{ESTIMATE_PREFIX} after the room of the LAST scene ({name}) is named, the text goes on for {len(tk) - last_pos} words "
                   f"(about {p['visible_secs']:.1f} s on screen) but only about {allowed} words may follow from its first word to the end of the text, "
                   f"the invitation to contact the agency included: name that room earlier (not in the last sentence) and keep the invitation to at most 7 words")
        elif p["kind"] == "too_slow":
            msg = (f"{ESTIMATE_PREFIX} scene {i + 1} ({name}) would stay on screen about {p['visible_secs']:.1f} s but at most {hi:.1f} s: "
                   f"the text spoken before the room of the next scene is named is about {w} words too long: cut about {w} words there, or name that room earlier")
        else:
            msg = (f"{ESTIMATE_PREFIX} scene {i + 1} ({name}) would stay on screen only about {p['visible_secs']:.1f} s but at least {lo:.1f} s: "
                   f"add about {w} words (a real fact from the listing) before the room of the next scene is named, or name that room later")
        if i == 0:
            msg += f" (the first room must be named within about {int(round((hi + st.LEAD_BEFORE_WORD) * wps))} words from the start of the text)"
        out.append(msg)
    return out[:2]     # a bad first clip shifts every later one: the model fixes the first problems, the next check reports the rest


def validate_free_text(text: str, anchors: list, description: str, agency_name: str = None, price: str = None,
                       split_fn=None, scenes: int = SCENES, labels: list = None, check_timing: bool = True) -> list:
    """Problems of the free narration (empty list = accepted). Same fact check as validate(), per spoken sentence."""
    import word_align as wa
    problems = []
    if not text or "\n" in text:
        return ["the text is empty or has line breaks"]
    n_words = len(words(text))
    if n_words < FREE_MIN_WORDS or n_words > FREE_MAX_WORDS:
        problems.append(f"the text has {n_words} words, it must have {PROMPT_WORDS} (never fewer than {FREE_MIN_WORDS} or more than {FREE_MAX_WORDS}): it must last about {TARGET_SPEECH_SECS} seconds, never more than {MAX_SPEECH_SECS}")
    desc = _norm(description)
    desc_numbers = _number_tokens(description)
    price_numbers = (_number_tokens(price) if price else set()) | _price_tokens(description)
    agency_n = re.sub(r"[^a-z0-9àèéìòù ]", "", _norm(agency_name)) if agency_name else ""
    sentences = split_fn(text) if split_fn is not None else [x for x in re.split(r"(?<=[.!?])\s+", text) if x]
    if not sentences:
        return ["no sentences found in the text"]
    for i, sent in enumerate(sentences):
        problems.extend(_fact_problems(sent, f"sentence {i + 1}", _norm(sent), desc, desc_numbers, price_numbers))
    first, last = _norm(sentences[0]), _norm(sentences[-1])
    says_sale, says_rent = "vendita" in first, "affitto" in first
    if not (says_sale or says_rent):
        problems.append("the first sentence must say 'in vendita' or 'in affitto'")
    if says_sale and not any(k in desc for k in ("vendita", "vendesi", "vendiamo", "vendere")):
        problems.append("the first sentence says 'in vendita' but the listing text does not")
    if says_rent and not any(k in desc for k in ("affitto", "affittasi", "locazione", "locare")):
        problems.append("the first sentence says 'in affitto' but the listing text does not")
    if agency_n:
        strip = lambda t: re.sub(r"[^a-z0-9àèéìòù ]", "", t)
        if agency_n not in strip(first):
            problems.append(f"the first sentence must name the agency ({agency_name})")
        if agency_n not in strip(last):
            problems.append(f"the last sentence must name the agency ({agency_name}) and invite to contact it")

    tk = wa.tokens(text)
    seen_scenes, last_pos = set(), -1
    for a in sorted(anchors or [], key=lambda x: x.get("scene", 0)):
        sc, phrase = a.get("scene"), a.get("phrase", "")
        if not isinstance(sc, int) or sc < 2 or sc > scenes:
            problems.append(f"anchor scene {sc}: must be between 2 and {scenes}")
            continue
        if sc in seen_scenes:
            problems.append(f"anchor scene {sc}: given twice")
            continue
        seen_scenes.add(sc)
        n_tok = len(wa.tokens(phrase))
        if n_tok < 1 or n_tok > 4:
            problems.append(f"anchor scene {sc}: the phrase must be 1 to 3 words ('{phrase}')")
            continue
        hits = wa.find_phrase(tk, phrase)
        if len(hits) != 1:
            problems.append(f"anchor scene {sc}: the phrase '{phrase}' must appear exactly once in the text (found {len(hits)})")
            continue
        if hits[0] <= last_pos:
            problems.append(f"anchor scene {sc}: '{phrase}' comes before the phrase of an earlier scene: rooms must be named in the order of the scenes")
        last_pos = max(last_pos, hits[0])
    if len([a for a in (anchors or []) if isinstance(a, dict)]) > MAX_ANCHORS:
        problems.append(f"{len(anchors)} rooms are named: there is no time for that in 30 seconds, name at most {MAX_ANCHORS} highlights (2 or 3) and leave the other rooms out")
    if check_timing and not problems:     # Patch L: only when the text is otherwise valid (a wrong text needs rewriting anyway)
        problems.extend(estimate_timing_problems(text, anchors, labels, scenes))
    return problems


def build_anchor_feedback(problems: list, anchors_info: list, labels: list, words_per_sec: float,
                          previous_text: str = None, speech_secs: float = None) -> str:
    """Tells the model, in words it can act on, why the MEASURED timing of its text was rejected.
    problems: scene_timing.plan_from_anchors()['problems']; anchors_info: [{"scene", "phrase", "word_at"}]."""
    lines = []
    by_scene = {a["scene"]: a for a in anchors_info}
    for p in problems:
        i = p["clip"]                       # clip i lasts from scene i's cut to scene i+1's cut
        lo, hi = p["allowed_visible"]
        nm = labels[i] if i < len(labels) else f"scene {i + 1}"
        over = p["seconds_over"]
        words_n = max(1, int(round(over * words_per_sec)))
        if p["kind"] == "too_slow":
            lines.append(f"- Scene {i + 1} ({nm}) would stay on screen {p['visible_secs']:.1f} s but it can last at most {hi:.1f} s: "
                         f"the part of the text spoken during scene {i + 1} is about {words_n} words too long "
                         f"(or the room of scene {i + 2} is named too late): shorten it or name that next room earlier.")
        else:
            lines.append(f"- Scene {i + 1} ({nm}) would stay on screen only {p['visible_secs']:.1f} s but it needs at least {lo:.1f} s: "
                         f"add about {words_n} words (a real fact from the listing) before the room of scene {i + 2} is named, "
                         f"or name that next room later.")
    head = ""
    if previous_text:
        head = f"\n\nYour previous text was (edit THIS text, do not start from zero):\n{previous_text}"
    if speech_secs:
        head += (f"\nThe voice read it in {speech_secs:.1f} seconds ({len(words(previous_text or ''))} words); "
                 f"it must last about {TARGET_SPEECH_SECS} s and never more than {MAX_SPEECH_SECS} s.")
        if speech_secs > MAX_SPEECH_SECS:
            head += f" Remove about {int(round((speech_secs - TARGET_SPEECH_SECS) * words_per_sec))} words."
    return (head + "\n\nYour previous text was REJECTED after the voice was recorded and measured. The rooms were named at these seconds: "
            + ", ".join(f"scene {a['scene']} '{a['phrase']}' at {a['word_at']:.1f} s" for a in sorted(anchors_info, key=lambda x: x['scene']))
            + ".\nProblems:\n" + "\n".join(lines) + "\nWrite the whole JSON object again, fixing these timings, keeping every other rule.")


# ── Block narration (2026-10-24, Patch Q) ──────────────────────────────────────────────────────────────────
# Three blocks of two scenes each (see scene_timing.plan_blocks). The facts rules are the same as for the free text (validate_free_text
# is reused with the timing check switched off); the block lengths are judged on the MEASURED audio, never on the word count alone.
N_BLOCKS = 3
BLOCK_TARGET_WORDS = 17        # a block is about 8.2 s of voice: 2 short sentences
BLOCK_MIN_WORDS = 12           # below / above these the block is rejected before any voice is paid for
BLOCK_MAX_WORDS = 23
# words that name a room, by scene category: a block may only name the rooms of ITS two scenes
ROOM_KEYWORDS = {
    "living": ("soggiorno", "salone", "living", "zona giorno"),
    "kitchen": ("cucina", "cucinotto"),
    "bedrooms": ("camera", "camere", "zona notte"),
    "bathrooms": ("bagno", "bagni", "doppi servizi", "servizi igienici"),   # Patch R3: bare "servizi" ("servizi completi") is generic, not a room
    "outdoor": ("giardino", "terrazza", "terrazzo", "balcone", "esterni", "esterno", "cortile", "veranda", "patio"),
}


# Patch R (2026-10-24): each block = exactly 2 sentences, sentence k is heard while scene k of the block is shown.
SENTENCE_MIN_WORDS = 5
SENTENCE_MAX_WORDS = 13
LAST_SENTENCE_MAX_WORDS = 11     # Patch R5 (2026-10-25): sentence 2 of block 3 = one fact + 0.6 s pause + "contatta <agency>"; at 13 words (like the others) it
                                 # needs ~6.8 s and the last picture cannot be slowed enough (simulation: last block was the cause of every real failure)
LAST_SENTENCE_MIN_FACT_WORDS = 3


def closing_budget(agency_name: str = None) -> dict:
    """Words available in sentence 2 of the last block: {"invitation": words of "contatta <agency>", "total": max words of the whole
    sentence, "fact": max words of the fact before the invitation}. Longer agency names get a little more room (never fewer than
    LAST_SENTENCE_MIN_FACT_WORDS words of fact)."""
    inv = 1 + max(1, len(words(agency_name or "l'agenzia")))
    total = max(LAST_SENTENCE_MAX_WORDS, inv + LAST_SENTENCE_MIN_FACT_WORDS)
    return {"invitation": inv, "total": total, "fact": total - inv}


MAX_ROOMS_NAMED = 3     # Michele 2026-10-23/25: name only 2-3 highlight rooms; a general sentence over any scene is fine
ROOM_WORD_EARLY_SECS = 0.0     # a room word may start no earlier than the cut to its scene ...
ROOM_WORD_LATE_SECS = 0.3      # ... and no later than this long before the cut away from it


def scene_of_sentence(scene_sequence: list, block: int, sentence: int):
    """The category of the scene that the sentence `sentence` (0/1) of block `block` is heard over."""
    i = block * 2 + sentence
    return scene_sequence[i] if 0 <= i < len(scene_sequence) else None


def named_rooms(sentence: str) -> set:
    """The room categories a sentence names (ROOM_KEYWORDS)."""
    import word_align as wa
    tk = wa.tokens(sentence)
    return {cat for cat, kws in ROOM_KEYWORDS.items() if any(wa.find_phrase(tk, kw) for kw in kws)}


def block_scene_groups(scene_sequence: list, per_block: int = 2) -> list:
    return [list(scene_sequence[i:i + per_block]) for i in range(0, len(scene_sequence), per_block)]


def build_blocks_prompt(description: str, address: str, agency_name: str, labels: list, scene_sequence: list) -> str:
    """labels: the Italian name of what each of the 6 scenes shows, in video order. The text comes back as 3 blocks of 2 sentences;
    sentence k of a block is heard while scene k of that block is shown (Patch R)."""
    agency = agency_name or "(agency name not available: say 'l'agenzia')"
    agency_it = agency_name or "l'agenzia"
    scene_lines = "\n".join(f"Scene {i + 1}: {label}" for i, label in enumerate(labels))
    slot_lines = []
    for b in range(N_BLOCKS):
        for k in range(2):
            i = b * 2 + k
            cat = scene_sequence[i] if i < len(scene_sequence) else None
            if cat in ROOM_KEYWORDS:
                rule = ("may name this room (" + ", ".join(ROOM_KEYWORDS[cat]) + ") ONLY if it is a real highlight of this property, with one fact about it; "
                        "otherwise speak of the property in general. Name no other room")
            else:
                rule = "speak of the property in general (no room names)"
            slot_lines.append(f"- Block {b + 1}, sentence {k + 1} (heard over scene {i + 1}: {labels[i] if i < len(labels) else '?'}): {rule}")
    slots = "\n".join(slot_lines)
    _cb = closing_budget(agency_name)
    return f"""You write the Italian voiceover of a 30-second real estate video. The video shows 6 scenes of 5 seconds, in this order:
{scene_lines}

The voice is ONE narration written as {N_BLOCKS} BLOCKS. Every block has EXACTLY 2 short sentences: the first sentence is heard while the first scene of the block is on screen, the second sentence while the second scene is on screen. So each sentence must talk about the picture it is heard over, in the order of the scenes:
{slots}

LENGTH: each sentence has {SENTENCE_MIN_WORDS}-{SENTENCE_MAX_WORDS} words (about 8, spoken in about 4 seconds); each block about {BLOCK_TARGET_WORDS} words in total (never fewer than {BLOCK_MIN_WORDS} or more than {BLOCK_MAX_WORDS}). EXCEPTION: sentence 2 of block 3 (the last one) has AT MOST {_cb["total"]} words in total, the invitation included ("contatta {agency_it}" takes {_cb["invitation"]} of them, so the fact before it has at most {_cb["fact"]} words) - it is the longest to speak because of the pause before the invitation. The voice speaks about 2.1 words per second. The durations are measured after the voice is recorded and a sentence that is too long or too short is sent back to you, so write the length with care.

Listing text:
---
{description}
---
Address: {address or 'not specified'}
Agency: {agency}

CONTENT:
- Block 1, sentence 1: the agency presenting the property ("{agency_name or "L'agenzia"} presenta ..."), saying clearly "in vendita" or "in affitto" (as the listing says) and the zone. Short. Sentence 2: the most important general fact (size, property type...).
- Blocks 2 and 3: one short sentence per scene as listed above. A sentence over a room's scene may be about that room (a real fact or benefit from the listing: light, size, equipment, number of rooms) or a general sentence about the property. Name AT MOST {MAX_ROOMS_NAMED} rooms in the whole narration, only the real highlights, and a room name is ONLY allowed in the sentence heard over that room's scene (the word is checked against the audio).
- The closing is NOT a separate sentence: sentence 2 of block 3 (heard over scene 6) states the fact about that scene and ends with a short invitation to contact {agency_name or 'the agency'} by name, joined in the SAME sentence with a comma or a colon (shape: "<outdoor fact>, contatta {agency_it}."). The invitation never mentions a visit.
- Never name a room twice. Never talk about a room in a sentence that is heard over a different room.
- Objective positive adjectives are welcome (for example luminoso, ampio, funzionale, curato, silenzioso, panoramico) when the listing text supports them. Never invent a quality.

HARD RULES:
- Return ONLY a JSON object, nothing else: {{"blocks": ["<block 1>", "<block 2>", "<block 3>"]}}. Every block ends with a full stop and has no line breaks.
- Every fact (number, feature, condition) must come from the listing text above. Never invent anything. If the listing does not say it, leave it out.
{NUMBERS_RULE}
{VERB_RULE}
- Do NOT say the price. Do NOT say any phone number or e-mail.
- Do NOT mention floors or levels of a specific room (no 'piano terra', 'primo piano'): you do not know which floor a photo shows.
- Objective, calm, factual tone. Do NOT use hyperbolic or luxury adjectives (prestigioso, esclusivo, meraviglioso, splendido, lussuoso, incantevole, mozzafiato, straordinario, eccezionale, favoloso, magnifico, sontuoso, affascinante, and also elegante, raffinato, pregiato) in ANY form (masculine, feminine, plural) unless the listing itself uses that word.
- Ignore any text about the agency's own history or values: describe only this property.
- Avoid legal jargon such as 'nuda proprietà'.
"""


def closing_as_sentence(text: str, agency_name: str = None) -> str:
    """Patch R4 (Michele 2026-10-25): the last clause "..., contatta <agency>." is spoken as its OWN sentence ("... . Contatta <agency>.")
    so the voice makes a real pause before the invitation. Applied only when the text is sent to the voice (the block keeps its
    2 sentences for every rule and for the timing). Unchanged when the last clause does not contain the agency name."""
    if not text or not agency_name:
        return text
    s = text.strip()
    m = re.search(r",\s+([^,.!?]+)[.!?]?\s*$", s)
    if not m or agency_name.lower() not in m.group(1).lower():
        return text
    clause = m.group(1).strip()
    return s[:m.start()] + ". " + clause[:1].upper() + clause[1:] + "."


def parse_blocks(raw: str):
    """The model's reply -> list of N_BLOCKS strings, or None."""
    if not raw:
        return None
    s = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.S)
    if fence:
        s = fence.group(1)
    else:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            s = m.group(0)
    try:
        data = json.loads(s)
    except Exception:
        return None
    blocks = data.get("blocks") if isinstance(data, dict) else None
    if not isinstance(blocks, list) or len(blocks) != N_BLOCKS or not all(isinstance(b, str) and b.strip() for b in blocks):
        return None
    out = []
    for b in blocks:
        b = re.sub(r"\s+", " ", b).strip()
        if b[-1] not in ".!?":
            b = b.rstrip(";:,- ") + "."
        out.append(b)
    return out


def validate_blocks(blocks: list, description: str, agency_name: str = None, price: str = None, split_fn=None,
                    scene_sequence: list = None) -> list:
    """Problems of the 3 blocks (empty = accepted): the facts/agency/sale-rent rules of the free text, a word band per block,
    and the room rule (a block may name only the rooms of its own two scenes)."""
    import word_align as wa
    if not isinstance(blocks, list) or len(blocks) != N_BLOCKS:
        return [f"{N_BLOCKS} blocks are needed"]
    problems = []
    for b, text in enumerate(blocks):
        n = len(words(text))
        if n < BLOCK_MIN_WORDS or n > BLOCK_MAX_WORDS:
            problems.append(f"block {b + 1} has {n} words: it must have about {BLOCK_TARGET_WORDS} (never fewer than {BLOCK_MIN_WORDS} or more than {BLOCK_MAX_WORDS})")
    problems.extend(validate_free_text(" ".join(blocks), [], description, agency_name, price, split_fn=split_fn, check_timing=False))
    if scene_sequence and split_fn:
        total_named = 0
        for b, text in enumerate(blocks):
            sents = split_fn(text)
            if len(sents) != 2:
                problems.append(f"block {b + 1} has {len(sents)} sentences: it must have EXACTLY 2 (the first is heard over scene {2 * b + 1}, the second over scene {2 * b + 2})")
                continue
            for k, sent in enumerate(sents):
                n = len(words(sent))
                if n < SENTENCE_MIN_WORDS or n > SENTENCE_MAX_WORDS:
                    problems.append(f"block {b + 1}, sentence {k + 1} has {n} words: each sentence must have {SENTENCE_MIN_WORDS}-{SENTENCE_MAX_WORDS} words (about 8)")
                if b == N_BLOCKS - 1 and k == 1:
                    cb = closing_budget(agency_name)
                    if n > cb["total"]:
                        problems.append(f"block {b + 1}, sentence 2 has {n} words: the last sentence has AT MOST {cb['total']} words in total, the invitation "
                                        f"('contatta ...', {cb['invitation']} words) included, so the fact before it has at most {cb['fact']} words")
                cat = scene_of_sentence(scene_sequence, b, k)
                found = named_rooms(sent)
                wrong = sorted(found - {cat})
                if wrong:
                    problems.append(f"block {b + 1}, sentence {k + 1} is heard over scene {2 * b + k + 1} ({cat}) but names {', '.join(wrong)}: "
                                    f"talk only about what scene {2 * b + k + 1} shows, or about the property in general")
                total_named += len(found & {cat})
        if total_named > MAX_ROOMS_NAMED:
            problems.append(f"{total_named} rooms are named: name at most {MAX_ROOMS_NAMED} (only the real highlights); speak of the property in general in the other sentences")
    return problems


def check_room_words(blocks: list, scene_sequence: list, word_times: list, cuts: list, split_fn,
                     early: float = ROOM_WORD_EARLY_SECS, late: float = ROOM_WORD_LATE_SECS) -> list:
    """The check with the real audio (Michele 2026-10-25): every room NAMED in the narration must be said while the picture of
    that room is on screen. word_times: (start, end) for every token of " ".join(blocks) (word_align.align); cuts: the cut
    times of the plan (cuts[i] .. cuts[i+1] = scene i). Returns one dict per named room:
    {"block","sentence","scene" (1-based),"room","word","at","window":[from,to],"ok","kind":"early"|"late"|None}."""
    import word_align as wa
    full = wa.tokens(" ".join(blocks))
    out, offset = [], 0
    for b, text in enumerate(blocks):
        for k, sent in enumerate(split_fn(text)):
            tk = wa.tokens(sent)
            cat = scene_of_sentence(scene_sequence, b, k)
            for room in named_rooms(sent) & {cat}:
                for kw in ROOM_KEYWORDS.get(room, ()):
                    hit = wa.find_phrase(tk, kw)
                    if not hit:
                        continue
                    idx = offset + hit[0]
                    if idx >= len(word_times):
                        break
                    t = float(word_times[idx][0])
                    i = b * 2 + k
                    lo, hi = float(cuts[i]) + early, float(cuts[i + 1]) - late
                    kind = "early" if t < lo else ("late" if t > hi else None)
                    out.append({"block": b + 1, "sentence": k + 1, "scene": i + 1, "room": room, "word": kw, "at": round(t, 3),
                                "window": [round(lo, 3), round(hi, 3)], "ok": kind is None, "kind": kind})
                    break
            offset += len(tk)
    return out


def build_word_check_feedback(violations: list, blocks: list) -> str:
    """The audio was transcribed: a room word is said outside the time its picture is on screen."""
    lines = []
    for v in violations:
        when = "before" if v["kind"] == "early" else "after"
        lines.append(f"- Block {v['block']}, sentence {v['sentence']}: the word '{v['word']}' is said at {v['at']:.1f} s, {when} the picture of that room is on screen "
                     f"({v['window'][0]:.1f}-{v['window'][1]:.1f} s). Remove the room name from this block (speak of the property in general) "
                     f"or change the sentences before it so that '{v['word']}' comes later/earlier.")
    return ("\n\nYour previous blocks were:\n" + json.dumps({"blocks": blocks}, ensure_ascii=False)
            + "\n\nThe voice was recorded and the words were timed. Problems:\n" + "\n".join(lines)
            + "\nReturn the whole JSON object again. Keep every sentence that is not mentioned above EXACTLY as it is.")


def build_sync_feedback(clip_problems: list, blocks: list, sentence_secs: list = None) -> str:
    """After the voice was placed: scene i (0-based) is heard with sentence i (block i//2, sentence i%2). A clip that would have
    to play slower than allowed (too_slow) has a sentence that is too long; one too fast (too_fast), a sentence that is too short."""
    lines = []
    by_clip = {int(p["clip"]): p for p in clip_problems}
    for p in clip_problems:
        i = int(p["clip"]); b, k = i // 2, i % 2
        prev = by_clip.get(i - 1)
        if k == 1 and prev is not None and prev["kind"] != p["kind"]:
            continue          # a knock-on of the sentence before it (a too short sentence makes the next picture too long): fix the first only
        secs = round(float(p.get("seconds_over", 0)), 1)
        if p["kind"] == "too_slow":
            lines.append(f"- Block {b + 1}, sentence {k + 1} (scene {i + 1}) is about {secs} s too long for its picture: shorten THAT sentence by about {max(2, int(round(secs * 2.1)) + 1)} words (aim well inside the limit, not at its edge).")
        else:
            lines.append(f"- Block {b + 1}, sentence {k + 1} (scene {i + 1}) is about {secs} s too short for its picture: lengthen THAT sentence by about {max(2, int(round(secs * 2.1)) + 1)} words (a real fact about the same room).")
    return ("\n\nYour previous blocks were:\n" + json.dumps({"blocks": blocks}, ensure_ascii=False)
            + "\n\nThe voice was recorded and each sentence was placed over its scene; the pictures can only be sped up or slowed down a little. Problems:\n"
            + "\n".join(lines) + "\nReturn the whole JSON object again. Keep every sentence that is not mentioned above EXACTLY as it is.")


def build_block_feedback(plan_problems: list, durations: list, blocks: list) -> str:
    """Tells the model, in seconds and words, which block is outside its slot after the voice was recorded and measured."""
    lines = []
    for p in plan_problems:
        j = p["block"]
        n = max(1, len(words(blocks[j])))
        wps = n / max(float(durations[j]), 1.0)
        k = max(1, int(round(p["seconds_over"] * wps)) + 1)
        if p["kind"] == "too_long":
            lines.append(f"- Block {j + 1} lasts {durations[j]:.1f} s ({n} words) and does not fit its slot: remove about {k} words (keep the facts that matter most).")
        else:
            lines.append(f"- Block {j + 1} lasts only {durations[j]:.1f} s ({n} words) and leaves a silence: add about {k} words (a real fact from the listing).")
    return ("\n\nYour previous blocks were:\n" + json.dumps({"blocks": blocks}, ensure_ascii=False)
            + "\n\nThe voice was recorded and measured; the blocks must fit their slots. Problems:\n" + "\n".join(lines)
            + "\nReturn the whole JSON object again. Keep every block that is not mentioned above EXACTLY as it is; change only the blocks listed.")
