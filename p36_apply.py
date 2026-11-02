#!/usr/bin/env python3
"""p36 (2026-11-02, job de90cbaf): narration names the PLACE (Relinx/GIAL payload has no address: property_name is passed as the address hint),
uses layout facts, allows the floor of the whole property, more vague-phrase filters. Idempotent, asserts every anchor, .bak_p36 backups. Run from repo root."""
import shutil
SS = [
 ("Address: {address or 'not specified'}\nAgency: {agency}",
  "Address / listing title (the place name in it, for example the town, is the ZONE): {address or 'not specified'}\nAgency: {agency}"),
 ("saying clearly \"in vendita\" or \"in affitto\" (as the listing says; if the listing says neither sale nor rent, say neither) and the zone. Short.",
  "saying clearly \"in vendita\" or \"in affitto\" (as the listing says; if the listing says neither sale nor rent, say neither) and the PLACE (the town or neighbourhood named in the address, the listing title or the listing text, for example \"ad Albano Laziale\": always name it when any of them gives one; never write only \"vicino al centro\"). Short."),
 ("- Never name a room twice.",
  "- LAYOUT FACTS: the listing text usually gives the plain structure (the floor of the whole property such as \"al piano terra\", the number of bedrooms and bathrooms, an entrance, a private courtyard or garden, a cellar, a parking space). When there is no striking feature, use these facts, one per sentence, instead of vague words about light or proportions. Never write sentences made only of vague impressions (\"proporzioni accoglienti\", \"illuminazione diffusa\", \"luce dalle finestre\").\n- Never name a room twice."),
 ("- Do NOT mention floors or levels of a specific room (no 'piano terra', 'primo piano'): you do not know which floor a photo shows.",
  "- Do NOT tie a floor to a specific room or photo (no 'la camera al primo piano'): you do not know which floor a photo shows. The floor of the WHOLE property (\"appartamento al piano terra\") is a property fact from the listing and is allowed."),
 ('"ambiente accogliente", "atmosfera accogliente", "dettagli di pregio")',
  '"ambiente accogliente", "atmosfera accogliente", "dettagli di pregio",\n                   "proporzioni accoglienti", "ben definit", "illuminazione diffusa", "luce diffusa", "luce naturale dalle finestre", "spazio luminoso")'),
]
API = [("description_full, None, None, payload.voice_id or None, False,",
        "description_full, (None if (payload.property_name or \"\").strip() in (\"\", \"Property\") else payload.property_name.strip()), None, payload.voice_id or None, False,")]
def go(path, reps, scoped=0):
    s = open(path).read(); shutil.copy(path, path + ".bak_p36"); done = 0
    for n, (old, new) in enumerate(reps):
        if new in s: continue
        if path == "scene_script.py" and n < 4:      # prompt lines: only inside build_blocks_prompt (older prompts share some phrases)
            i = s.index("def build_blocks_prompt"); j = s.index("def closing_as_sentence"); t = s[i:j]
            assert t.count(old) == 1, ("anchor not found / ambiguous in build_blocks_prompt", old[:60])
            s = s[:i] + t.replace(old, new) + s[j:]
        else:
            assert s.count(old) == 1, ("anchor not found / ambiguous", old[:60]); s = s.replace(old, new)
        done += 1
    open(path, "w").write(s); print(path, "replacements applied:", done)
go("scene_script.py", SS); go("api_server.py", API)
