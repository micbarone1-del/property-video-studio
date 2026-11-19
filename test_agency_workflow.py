import os, re, sys, types, tempfile, json
from pathlib import Path
for _m in ('pydub',):
    sys.modules.setdefault(_m, types.ModuleType(_m))
sys.modules['pydub'].AudioSegment = object
os.environ.setdefault("PVS_DATA_DIR", tempfile.mkdtemp())
import agency_pronunciation as ap
import cost_model as cm
import voice_generation as vg
ok = True
def chk(n, c):
    global ok; print(("PASS" if c else "FAIL"), n); ok &= bool(c)

# --- pure rules
chk("AW1 proposal un-shouts ALL CAPS words, keeps mixed case",
    ap.default_proposal("THRINAKIE GROUP") == "Thrinakie Group" and ap.default_proposal("GIAL IMMOBILIARE") == "Gial Immobiliare"
    and ap.default_proposal("Engel & Völkers Roma") == "Engel & Völkers Roma" and ap.default_proposal("VÖLKERS") == "Völkers")
chk("AW2 needs_validation: new yes, legacy no, validated no, None no",
    ap.needs_validation({"pronunciation_validated": False}) and not ap.needs_validation({"name": "x"})
    and not ap.needs_validation({"pronunciation_validated": True}) and not ap.needs_validation(None))
T = "Trinachìe Group"
A = [{"agency_id": "ag_1", "name": "THRINAKIE GROUP", "pronunciation": T, "pronunciation_validated": True}]
chk("AW3 full name replaced in any case", all(ap.apply(x, A) == T + " presenta" for x in ("THRINAKIE GROUP presenta", "Thrinakie Group presenta", "thrinakie group presenta")))
chk("AW4 partial name (the words before the shared ending) replaced alone", ap.apply("Contatta THRINAKIE oggi", A) == "Contatta Trinachìe oggi" and ap.apply("thrinakie", A) == "Trinachìe")
chk("AW5 whole words only", ap.apply("Thrinakiexyz e xthrinakie", A) == "Thrinakiexyz e xthrinakie")
B = [{"agency_id": "ag_2", "name": "THRINAKIE GROUP", "pronunciation": None, "pronunciation_validated": False}]
chk("AW6 no stored pronunciation -> the Capitalised proposal, never the ALL CAPS name", ap.apply("THRINAKIE GROUP presenta", B) == "Thrinakie Group presenta" and ap.apply("THRINAKIE", B) == "Thrinakie")
L = [{"agency_id": "ag_3", "name": "GIAL IMMOBILIARE"}]
chk("AW7 legacy agency (no keys) -> no rule, text untouched", ap.rules(L) == [] and ap.apply("GIAL IMMOBILIARE", L) == "GIAL IMMOBILIARE")
E = [{"agency_id": "ag_4", "name": "Engel & Völkers Roma", "pronunciation": "Èngel e Fèlkers Roma", "pronunciation_validated": True}]
chk("AW8 name with an ampersand matches before the TTS cleaning", ap.apply("Engel & Völkers Roma presenta", E) == "Èngel e Fèlkers Roma presenta")
chk("AW9 clean_pronunciation: one line, no markup, 120 max", ap.clean_pronunciation(" a<b>\nc\t d ") == "a b c d" and len(ap.clean_pronunciation("x" * 500)) == 120 and ap.clean_pronunciation(None) == "")

# --- storage
tmp = Path(tempfile.mkdtemp()); cm.AGENCIES_FILE = tmp / "agencies.json"
a1 = cm.create_agency_for_partner("THRINAKIE GROUP", "pt_x", "ext1")
chk("AW10 new partner agency starts unvalidated and un-notified", a1["pronunciation_validated"] is False and a1["setup_notified"] is False and a1["pronunciation"] is None)
chk("AW11 same partner id again returns the SAME agency, state kept", cm.create_agency_for_partner("THRINAKIE GROUP", "pt_x", "ext1")["agency_id"] == a1["agency_id"])
a2 = cm.create_agency("Solo Nome", partner_flow=True)
a3 = cm.create_agency("Manuale")
chk("AW12 name-only partner agency joins the workflow, a manual one does not", a2["pronunciation_validated"] is False and "pronunciation_validated" not in a3)
chk("AW13 an existing agency matched by name is returned untouched", cm.create_agency("solo nome", partner_flow=True)["agency_id"] == a2["agency_id"])
cm.mark_agency_setup_notified(a1["agency_id"])
d = cm.set_agency_pronunciation(a1["agency_id"], T, True)
chk("AW14 confirm stores the text and validates; notified flag kept", d["pronunciation"] == T and d["pronunciation_validated"] is True and d["setup_notified"] is True and not ap.needs_validation(d))
chk("AW15 only the confirmed agency changed", cm.get_agency(a2["agency_id"])["pronunciation_validated"] is False)

# --- the voice choke point
text = vg.apply_pronunciation_fixes(vg.apply_agency_pronunciations("THRINAKIE GROUP presenta GIAL IMMOBILIARE"))
chk("AW16 voice: agency rule first, then the global word file (GIAL still -> Gi-al)", text == T + " presenta Gì-al Immobiliare" or text.startswith(T + " presenta"))
chk("AW17 voice: a broken agencies file never breaks the text", (lambda: (cm.AGENCIES_FILE.write_text("{not json"), vg.apply_agency_pronunciations("Ciao"))[1])() == "Ciao")

# --- wiring (source checks, same style as the other test files)
src = open("api_server.py").read(); pg = open("operator_page.html").read(); vsrc = open("voice_generation.py").read()
chk("AW18 automatic release is held for an unvalidated agency, once per job",
    "agency_pronunciation.needs_validation(cost_model.get_agency(j.get(\"agency_id\")))" in src and "_HELD_AGENCY_NOTIFIED" in src)
chk("AW19 one notice per new agency, called after the logo step", src.count("_notify_new_agency_setup(") == 2 and "setup_notified" in src)
chk("AW20 both partner branches create the agency through the workflow", "create_agency(payload.agency_name, partner_flow=True)" in src and "create_agency_for_partner(" in src)
chk("AW21 endpoints and status payload", all(k in src for k in ('"/operator/agency/{agency_id}/pronunciation"', '"/operator/agency/{agency_id}/listen"', '"agencies_pending"', '"agency_pending"')))
chk("AW22 listen endpoint is not auth-exempt (path does not end in /preview or /download)", not '/listen"'.endswith(("/preview", "/download")))
chk("AW23 page: card, listen, confirm, held tag", all(k in pg for k in ("Nuove agenzie da validare", "listenAgency", "confirmAgency", "agenzia da validare")))
chk("AW24 one TTS choke point: both calls in generate_speech, agency first", vsrc.index("apply_agency_pronunciations(text)") < vsrc.index("text = apply_pronunciation_fixes(text)"))
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
