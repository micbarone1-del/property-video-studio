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
- Numbers: copy them as the listing writes them (e.g. '650 metri quadri').
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
