# RELINX_QUESTIONS.md -- punti aperti con Relinx (riscritto 2026-10-09)

_Versione breve. La lista di 45 domande della prima bozza e' ritirata (resta nella storia git): la maggior parte era gia' coperta dallo scambio email 1-8 ottobre e dai test, oppure e' diventata una decisione o un'assunzione nostra (sotto). Le risposte vanno riportate in AUTOMATION_TEST_PLAN.md._

## Punti ancora aperti (testo per Relinx)
| ID | Punto | Chiude il rischio |
|---|---|---|
| Q1 | **Firma del webhook**: la attiviamo da subito (header HMAC con segreto condiviso) oppure per ora vi basta rileggere lo stato dalle nostre API? (Domanda del 2 ottobre, nessuna risposta nel thread.) | F33 |
| Q2 | **Durata del `video_url`** per la riproduzione nel CRM: quanto deve restare valido (es. 30 giorni)? | F35, F36 |
| Q3 | **Logo agenzia**: lo mandate come URL nel payload della richiesta, o preferite che lo carichiamo noi una tantum per agenzia? | F16, Q30 |
| Q4 | **Privacy**: vi mandiamo una bozza di accordo sul trattamento dei dati per i test (DPA_DRAFT.md). Chi la vede da parte vostra? La liberatoria delle agenzie copre l'elaborazione con servizi IA di terzi? (Domanda gia' posta l'8 ottobre, senza risposta.) | F39, F40 |
| Q5 | **Finestra di test**: una sessione concordata con scenari fissi, piu' una data di riserva. Fissiamo le date insieme. | G3 |

## Decisioni e assunzioni nostre (non sono domande)
- Referente Relinx per i test: Michele (Relinx), gia' concordato. Revisori: fase interna Michele + Michele (Relinx); pilota Michele + agenzia.
- Foto: assumiamo originali ad alta risoluzione, con ordine e categorie affidabili. Se cosi' non fosse, lo rileviamo nei test e lo segnaliamo.
- Etichetta: testo "Generated with AI", sempre in inglese, mai localizzata; niente logo Property Video Studio (white label).
- Qualita': specifica scritta da noi e inviata per conoscenza (QUALITY_SPEC_FOR_RELINX.md). Il feedback qualitativo di Relinx gia' dato a voce e' stato trasformato in richieste di aggiornamento.
- Gia' chiuso nei test e nel thread: schema della richiesta, lettura dello stato e `video_url` a `completed`, callback al rilascio, timeout della POST (corretto da loro il 3 ottobre).

## Commerciale
Prezzi, scaglioni e fatturazione: discussione separata a voce, non in questo elenco.
