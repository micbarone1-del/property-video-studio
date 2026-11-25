import os
import re
import requests
import mimetypes
from dotenv import load_dotenv
import logging as log
from pydub import AudioSegment

# Constants
load_dotenv()

TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "elevenlabs").strip().lower()

DEFAULT_VOICE_ID_ELEVENLABS = "b8jhBTcGAq4kQGWmKprT"
# 2026-11-19: the default Google voice is a knob (PVS_DEFAULT_VOICE, restart to apply) so it can be changed, and changed back, without a deploy.
# An id that is not in the registry below is ignored (the knob can never break the TTS): Leda, the voice used until now, stays the fallback.
FALLBACK_VOICE_GOOGLE       = "it-IT-Chirp3-HD-Leda"
_IT_VOICES = [
    {"id": "it-IT-Chirp3-HD-Leda",   "label": "Leda (femminile)"},
    {"id": "it-IT-Chirp3-HD-Aoede",  "label": "Aoede (femminile)"},
    {"id": "it-IT-Chirp3-HD-Kore",   "label": "Kore (femminile)"},
    {"id": "it-IT-Chirp3-HD-Charon", "label": "Charon (maschile)"},
    {"id": "it-IT-Chirp3-HD-Puck",   "label": "Puck (maschile)"},
    {"id": "it-IT-Chirp3-HD-Orus",   "label": "Orus (maschile)"},
]
DEFAULT_VOICE_ID_GOOGLE     = os.environ.get("PVS_DEFAULT_VOICE", "").strip() or FALLBACK_VOICE_GOOGLE
if DEFAULT_VOICE_ID_GOOGLE not in [v["id"] for v in _IT_VOICES]:
    print(f"[TTS] PVS_DEFAULT_VOICE={DEFAULT_VOICE_ID_GOOGLE!r} is not a known voice, using {FALLBACK_VOICE_GOOGLE}")
    DEFAULT_VOICE_ID_GOOGLE = FALLBACK_VOICE_GOOGLE
DEFAULT_VOICE_ID = DEFAULT_VOICE_ID_GOOGLE if TTS_PROVIDER == "google" else DEFAULT_VOICE_ID_ELEVENLABS

# 2026-10-08: language/voice registry -- single source of truth for which voices exist per language.
# Adding a language = adding one entry here (the UI menus read it through /tts/voices).
# NOTE: only the TTS voice is language-aware so far; narration prompts, captions,
# pronunciation fixes and UI strings are still Italian-only.
DEFAULT_LANGUAGE = "it-IT"
TTS_LANGUAGES = {
    "it-IT": {
        "label": "Italiano",
        "default_voice": DEFAULT_VOICE_ID_GOOGLE,
        "voices": _IT_VOICES,
    },
}


def language_of_voice(voice_id):
    """'it-IT' from 'it-IT-Chirp3-HD-Leda'; DEFAULT_LANGUAGE when not recognisable."""
    code = "-".join((voice_id or "").split("-")[:2])
    return code if code in TTS_LANGUAGES else DEFAULT_LANGUAGE


def resolve_voice(voice_id, language=None):
    """Always returns a usable voice. Google: must be in the registry, otherwise the language default
    (this is what stops a stray address or an ElevenLabs ID in the voice field from breaking TTS)."""
    voice_id = (voice_id or "").strip()
    if TTS_PROVIDER != "google":
        return voice_id or DEFAULT_VOICE_ID  # ElevenLabs IDs are free-form
    if any(voice_id == v["id"] for lang in TTS_LANGUAGES.values() for v in lang["voices"]):
        return voice_id
    if voice_id:
        print(f"[TTS] voice {voice_id!r} is not a known Google voice, using the default")
    return TTS_LANGUAGES[language if language in TTS_LANGUAGES else DEFAULT_LANGUAGE]["default_voice"]


ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
GOOGLE_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"

def apply_noise_gate(audio_segment, threshold_db=-32.0, chunk_size_ms=10, tail_only_ms=200):
    """
    Applies a simple noise gate to the audio to remove breathing/silence.
    If tail_only_ms is provided, it ONLY applies the gate to the last X milliseconds,
    leaving the rest of the speech completely untouched.
    """
    # Split audio into the untouched main part and the tail to be processed
    if tail_only_ms > 0 and len(audio_segment) > tail_only_ms:
        main_audio = audio_segment[:-tail_only_ms]
        target_audio = audio_segment[-tail_only_ms:]
    else:
        main_audio = audio_segment[:0] # Empty segment
        target_audio = audio_segment
        
    ranges_to_silence = []
    current_silence_start = None
    
    # Scan target audio loudness
    for i in range(0, len(target_audio), chunk_size_ms):
        chunk = target_audio[i:i+chunk_size_ms]
        
        if chunk.dBFS < threshold_db:
            if current_silence_start is None:
                current_silence_start = i
        else:
            if current_silence_start is not None:
                ranges_to_silence.append((current_silence_start, i))
                current_silence_start = None
                
    # Handle end of file
    if current_silence_start is not None:
        ranges_to_silence.append((current_silence_start, len(target_audio)))
        
    if not ranges_to_silence:
        return audio_segment # Return original if no silence found
        
    print(f"    -> Noise Gate: Detected {len(ranges_to_silence)} breath/silence segments in the last {tail_only_ms}ms.")
    
    cleaned_target = target_audio
    
    # Process in reverse order to maintain indices while constructing new audio
    for start, end in ranges_to_silence[::-1]:
        duration = end - start
        # Removed the 'if duration < 50' check here so it successfully processes small tails
            
        silence_chunk = AudioSegment.silent(duration=duration)
        
        # Replace the breathy section with pure silence
        cleaned_target = cleaned_target[:start] + silence_chunk + cleaned_target[end:]
        
    # Reattach the untouched main audio with the cleaned tail
    return main_audio + cleaned_target

# 2026-10-08: pronunciation corrections. One shared place (every TTS caller goes through generate_speech),
# applied to the text sent to the voice only -- stored job text and the UI are never changed.
_PRON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pronunciation_fixes.json")
_pron_cache = {"mtime": None, "rules": []}


def sanitize_for_tts(text):
    """2026-10-12: the Google voices are driven with SSML, so a raw '&' or '<' in the text made the whole request
    invalid (HTTP 400) and failed the job - e.g. the agency name "Engel & Völkers Roma" (every job of that agency).
    '&' is spoken as 'e'; '<' and '>' are dropped. Plain text only, like pronunciation_fixes.json."""
    import re
    text = re.sub(r"\s*&\s*", " e ", text)
    text = text.replace("<", " ").replace(">", " ")
    text = spoken_units(text)
    return re.sub(r"[ \t]{2,}", " ", text)


def spoken_units(text):
    """2026-10-25: square metres are always spoken 'metri quadri' (never 'mq' spelled letter by letter, never
    'metri quadrati'). Single authority for every provider (called from sanitize_for_tts, which generate_speech
    always applies). It also removes the full stop of the abbreviation ('mq. 60' made the voice stop after 'M-Q'
    because generate_speech adds a pause after every period)."""
    import re
    num = r"(\d+(?:[.,]\d+)?)"
    text = re.sub(r"(?<!\w)(?:mq|m\u00b2|m2)\.?\s+" + num + r"(?![\d.,]*\w)", r"\1 metri quadri", text, flags=re.I)  # 'mq. 60' -> '60 metri quadri'
    text = re.sub(num + r"\s*(?:mq|m\u00b2|m2)(?![\w\u00b2])", r"\1 metri quadri", text, flags=re.I)  # '60 mq' / '60m2'
    text = re.sub(r"(?<!\w)mq(?!\w)\.?", "metri quadri", text, flags=re.I)  # a bare 'mq'
    text = re.sub(r"\bmetri quadrati\b", "metri quadri", text, flags=re.I)
    # 2026-11-25 (Michele, real job da983c2e: '110,00 metri quadri' was read 'centodieci virgola zero zero'): a decimal part made only of zeros
    # (one or two digits: ',0' ',00' '.00') is never spoken. 'Exactly one or two zeros not followed by a digit' keeps '1.000' (thousands) and '2,50' intact.
    text = re.sub(r"(?<=\d)[.,]0{1,2}(?!\d)", "", text)
    return text


_IPA_SRC = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
_IPA_TOK = re.compile("([0-9a-f]+)_([0-9a-f]+)")


def _protect_ipa(value):
    """2026-11-19 (Michele): a rule value may carry an exact IPA pronunciation, written [[ipa|word]] (example: "[[trinaˈkie|Thrinakie]]").
    Chirp voices ignore written accents and move the stress from run to run; an IPA <phoneme> is followed. The segment is turned into a token
    made of hex digits (one \\w run, so no later rule can match inside it) and expanded by expand_ipa() AFTER the text is cleaned."""
    return _IPA_SRC.sub(lambda m: "" + m.group(1).strip().encode("utf-8").hex() + "_" + m.group(2).strip().encode("utf-8").hex() + "", value)


def expand_ipa(text, ssml=True):
    """The tokens of _protect_ipa become <phoneme alphabet="ipa" ph="..">word</phoneme> (Google SSML) or just the word (any other provider).
    An unsafe segment (a full stop would get a pause inserted inside the tag, or a character that breaks the attribute) falls back to the plain word."""
    def one(m):
        ph, word = bytes.fromhex(m.group(1)).decode("utf-8"), bytes.fromhex(m.group(2)).decode("utf-8")
        if not ssml or not ph or "." in ph or any(c in ph + word for c in '<>&"'):
            return word
        return '<phoneme alphabet="ipa" ph="' + ph + '">' + word + '</phoneme>'
    return _IPA_TOK.sub(one, text)


def apply_pronunciation_fixes(text):
    import re, json
    try:
        mtime = os.path.getmtime(_PRON_PATH)
    except OSError:
        return text
    try:
        if _pron_cache["mtime"] != mtime:
            with open(_PRON_PATH, encoding="utf-8") as f:
                data = json.load(f)
            rules = [(re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)"), _protect_ipa(v))
                     for k, v in sorted(data.items(), key=lambda kv: -len(kv[0]))
                     if isinstance(k, str) and isinstance(v, str) and k and not k.startswith("_")]
            _pron_cache["mtime"], _pron_cache["rules"] = mtime, rules
        for rx, rep in _pron_cache["rules"]:
            text = rx.sub(lambda m, r=rep: r, text)
    except Exception as e:
        print(f"[Pronunciation] ignoring fixes file ({e!r})")
    return text


def apply_agency_pronunciations(text):
    """2026-11-19: the agency names (agency_pronunciation.py): replaced whatever their case, BEFORE the global word file (which then still
    applies, e.g. Gial -> Gi-al). Never raises: a broken agencies file leaves the text as it is."""
    try:
        import agency_pronunciation, cost_model
        return agency_pronunciation.apply(text, cost_model.list_agencies())
    except Exception as e:
        print(f"[Pronunciation] agency names ignored ({e!r})")
        return text


def generate_speech(
    text, 
    output_path, 
    api_key=None, 
    voice_id=DEFAULT_VOICE_ID,
    title_pause=1.0,
    sentence_pause=0.2,
    noise_gate_threshold=-38.0
):
    """
    Generates Italian speech using ElevenLabs or Google Cloud TTS (set via
    TTS_PROVIDER env var), then applies a noise gate 
    to remove breathing sounds from the end before saving the final file.
    
    Args:
        text (str): The text to be spoken. First line is treated as Title.
        output_path (str): File path to save the final .mp3 audio.
        api_key (str): ElevenLabs API Key. Defaults to env variable.
        voice_id (str): The ElevenLabs Voice ID.
        title_pause (float): Seconds of silence after the first line.
        sentence_pause (float): Seconds of silence after each period.
        noise_gate_threshold (float): dB threshold for removing breath sounds.
    """
    # Guard against None voice_id (fallback to default)
    voice_id = resolve_voice(voice_id)  # 2026-10-08: invalid or foreign voices fall back to the default
    # 1. Get API Key
    key_env_var = "GOOGLE_TTS_API_KEY" if TTS_PROVIDER == "google" else "ELEVENLABS_API_KEY"
    key = api_key or os.environ.get(key_env_var)
    if not key:
        print(f"Error: {key_env_var} not found. Please set it or pass it as an argument.")
        return False

    text = apply_agency_pronunciations(text)  # 2026-11-19: agency names first (any case), then the global word file
    text = apply_pronunciation_fixes(text)  # 2026-10-08: single choke point for all TTS callers
    text = sanitize_for_tts(text)  # 2026-10-12: SSML-safe plain text (see sanitize_for_tts)
    text = expand_ipa(text, ssml=(TTS_PROVIDER == "google"))  # 2026-11-19: IPA pronunciations become <phoneme> tags (Google) after the cleaning
    print(f"Generating speech for: \"{text[:30]}...\"")
    
    # 2. Process Text for Pauses (SSML Injection)
    break_tag = f" <break time=\"{sentence_pause}s\" />"

    def add_breaks(segment):
        # Replace all periods with period + break
        processed = segment.replace(".", "." + break_tag)
        # Remove the break if it's at the very end of the string (ignoring whitespace)
        if processed.rstrip().endswith(break_tag.strip()):
            processed = processed[:processed.rfind(break_tag)]
        return processed

    # Treat the first line as the "Header/Title"
    parts = text.strip().split('\n', 1)

    if len(parts) == 2:
        title = parts[0]
        body = parts[1]
        processed_body = add_breaks(body)
        final_text = f"{title} <break time=\"{title_pause}s\" /> {processed_body}"
    else:
        # If no newline, just process the whole text as body
        final_text = add_breaks(text)

    try:
        # 3. Prepare & Send API Request (provider-specific)
        if TTS_PROVIDER == "google":
            lang_code = "-".join(voice_id.split("-")[:2])  # "it-IT" from "it-IT-Chirp3-HD-Leda"
            url = f"{GOOGLE_TTS_URL}?key={key}"
            headers = {"Content-Type": "application/json; charset=utf-8"}
            data = {
                "input": {"ssml": f"<speak>{final_text}</speak>"},
                "voice": {"languageCode": lang_code, "name": voice_id},
                "audioConfig": {"audioEncoding": "MP3"},
            }
            response = requests.post(url, json=data, headers=headers)
            if response.status_code != 200:
                print(f"  Error: Google TTS API returned {response.status_code}")
                print(f"  Details: {response.text}")
                return False
            audio_b64 = response.json().get("audioContent")
            if not audio_b64:
                print(f"  Error: Google TTS response had no audioContent: {response.text}")
                return False
            import base64
            audio_bytes = base64.b64decode(audio_b64)
        else:
            url = ELEVENLABS_TTS_URL.format(voice_id=voice_id)
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": key
            }
            data = {
                "text": final_text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.3,
                    "similarity_boost": 0.75,
                    "style": 0.8,
                    "use_speaker_boost": True
                }
            }
            response = requests.post(url, json=data, headers=headers)
            if response.status_code != 200:
                print(f"  Error: ElevenLabs API returned {response.status_code}")
                print(f"  Details: {response.text}")
                return False
            audio_bytes = response.content

        # 5. Save Audio to Temp File
        temp_path = f"temp_{os.path.basename(output_path)}"
        with open(temp_path, 'wb') as f:
            f.write(audio_bytes)

        # 6. Apply Noise Gate
        try:
            print(f"  Applying noise gate to last 200ms (Threshold: {noise_gate_threshold}dB)...")
            audio = AudioSegment.from_mp3(temp_path)
            cleaned = apply_noise_gate(audio, threshold_db=noise_gate_threshold)

            # 7. Export Cleaned Audio
            cleaned.export(output_path, format="mp3")
            print(f"  Audio cleaned and saved to: {output_path}")

        except Exception as e:
            print(f"  Error during noise gate processing: {e}")
            if os.path.exists(temp_path):
                os.rename(temp_path, output_path)
                print("  Saved original audio (uncleaned) due to error.")

        # 8. Cleanup Temp File
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return True

    except Exception as e:
        print(f"  Exception during speech generation: {e}")
        return False

if __name__ == "__main__":

    sample_news_text = ("Concepito come servizio museale aggiuntivo del vicino Museo dell’Ara Pacis e del complesso archeologico del Mausoleo di Augusto, Augusto Caffè è l’ennesimo progetto di ristorazione museale senza guizzi, in uno spazio unico al mondo. I limiti di gare d’appalto non aggiornate\n")

    print(generate_speech(sample_news_text, "saranno_audio.mp3"))
