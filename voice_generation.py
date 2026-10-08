import os
import requests
import mimetypes
from dotenv import load_dotenv
import logging as log
from pydub import AudioSegment

# Constants
load_dotenv()

TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "elevenlabs").strip().lower()

DEFAULT_VOICE_ID_ELEVENLABS = "b8jhBTcGAq4kQGWmKprT"
DEFAULT_VOICE_ID_GOOGLE     = "it-IT-Chirp3-HD-Leda"
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
        "voices": [
            {"id": "it-IT-Chirp3-HD-Leda",   "label": "Leda (femminile)"},
            {"id": "it-IT-Chirp3-HD-Aoede",  "label": "Aoede (femminile)"},
            {"id": "it-IT-Chirp3-HD-Kore",   "label": "Kore (femminile)"},
            {"id": "it-IT-Chirp3-HD-Charon", "label": "Charon (maschile)"},
            {"id": "it-IT-Chirp3-HD-Puck",   "label": "Puck (maschile)"},
            {"id": "it-IT-Chirp3-HD-Orus",   "label": "Orus (maschile)"},
        ],
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
            rules = [(re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)"), v)
                     for k, v in sorted(data.items(), key=lambda kv: -len(kv[0]))
                     if isinstance(k, str) and isinstance(v, str) and k and not k.startswith("_")]
            _pron_cache["mtime"], _pron_cache["rules"] = mtime, rules
        for rx, rep in _pron_cache["rules"]:
            text = rx.sub(lambda m, r=rep: r, text)
    except Exception as e:
        print(f"[Pronunciation] ignoring fixes file ({e!r})")
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

    text = apply_pronunciation_fixes(text)  # 2026-10-08: single choke point for all TTS callers
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