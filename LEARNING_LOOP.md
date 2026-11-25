# Ciclo di apprendimento: allucinazioni video e narrazione

Creato il 2026-11-24. Vive nella repo accanto a status.md e backlog.md. Stato di ogni punto: "non eseguito" resta "non eseguito" finche' non c'e' un output.

## 1. Perche' esiste
Le allucinazioni dei clip e gli errori di narrazione non si prevengono con un controllo a valle: il controllo qualita' e' la rete di sicurezza. La prevenzione e' cambiare gli INPUT prima di spendere (quale foto, quale movimento, quale bersaglio, quale regola di testo). Il ciclo impara dagli esiti che il sistema gia' produce e trasforma cio' che regge alla verifica in vincoli. Nessuna decisione per singolo video tocca Michele.

## 2. Gia' provato e chiuso (non rifare)
Varianti di prompt (round 5-6: nessuna piu' sicura; Luma senza seed ne' blocco camera); fotogramma finale, coppia di fotogrammi, zoom su ritaglio (aspetto rifiutato da Michele), parallasse con profondita', modelli di immagine alternativi, nuvola di punti, metrica di incoerenza, segnali di velocita'. Il tipo di stanza e il tipo di piano da soli NON predicono il rischio (statico 31%, avanzamento 27%, altro 31%). Il test a 360p e' un QC a basso costo, non prevenzione: non fa parte di questo ciclo.

## 3. Quello che esiste (nessun secondo registro)
| Fonte | Contenuto |
|---|---|
| scene_risk_events.jsonl (scene_risk.py) | job, scena, categoria, movimento, tier, fase (first/rework), verdetto |
| standard_shadow_events.jsonl (clip_standard.py) | new_max, giudice, domande extra (revealed_no, extended_scene), velocita', piano |
| job_meta.json | campi della scena (ancora, lato, profondita', superficie riflettente), modo narrazione, tentativi |
Il ciclo UNISCE queste fonti. Non scrive in nessuna.

## 4. Etichette (senza persone, tenute SEPARATE)
- l_qc: il primo controllo qualita' da' flag, reject o failed.
- l_persistent: dopo il rework il problema resta (solo per scene rifatte).
- l_detector: candidato (domande extra rivelato o scena estesa) e new_max > 0.05. Misurato in sample su 40 clip: 12/15 difettosi, 3/25 falsi allarmi; soglie scelte sugli stessi dati.
Limite noto: il giudice cambia verdetto tra due chiamate identiche sul 34% dei clip; le etichette sono rumorose. Per questo i risultati si leggono per etichetta, mai fusi in un numero. Verifica periodica dell'etichetta: accordo tra due formulazioni della domanda (fase 3).

## 5. Metodo (criteri scritti PRIMA di guardare i dati)
- Divisione per JOB (hash dell'id), 30% dei job tenuto da parte, mai per clip (le scene di un annuncio sono correlate).
- Una regola si TROVA sul 70%: almeno 10 scene, tasso almeno 1,5 volte la linea di base e limite inferiore di Wilson (circa 80%) sopra la linea di base.
- Una regola si TIENE solo se REGGE sul 30%: almeno 10 scene, tasso almeno 1,3 volte la linea di base del 30% e almeno 10 punti sopra.
- Pochi dati = "non abbastanza dati", mai una regola. Con il volume attuale (116 eventi in due settimane, pilota fermo) la prima esecuzione dira' quasi certamente cosi': e' il risultato corretto.
- Il codice e' learning_loop.py, i test sono test_learning_loop.py (L1-L12, con un segnale piantato e un falso schema piantato).

## 6. Fasi
1. **Fase 1 (fatta, offline, sola lettura):** learning_loop.py. Non e' importato da nessun modulo di produzione (test L11). Si lancia a mano sul server: `python3 learning_loop.py jobs`. Non ancora eseguito su dati veri.
   - 1b (da fare): caricare come seme i clip delle prove con le etichette di Michele gia' esistenti (circa 126 + 40 + 90, in jobs/_test_scratch), che oggi il programma salta. Sono dati gia' etichettati: nessun lavoro nuovo per lui.
2. **Fase 2, registrazione (tocca il percorso di generazione e di narrazione: punto di ritorno, prova sull'istanza finta, nessun deploy senza esito):** campi aggiunti ai registri esistenti, mai in un registro nuovo, mai con eccezioni che salgono: descrittore della foto della scena (dalla domanda unica gia' fatta a ogni foto), bersaglio generico o specifico, risoluzione, e per la narrazione il motivo di ogni rifiuto per tentativo (codice della regola), modello, modo e motivo del ripiego (oggi NON salvati in job_meta), caratteristiche dell'annuncio.
3. **Fase 3, in ombra:** il ciclo dice "avrei cambiato X" senza cambiare nulla; si conta quante volte e con quale esito. Scadenza: 40 scene che scattano o 14/12/2026, il primo dei due. Si misura anche l'accordo tra etichette.
4. **Fase 4, applicazione:** solo per regole che hanno retto in fase 3.

## 7. Cosa il ciclo puo' cambiare da solo, e cosa no
Puo' (vincoli morbidi nella scelta): tipo di movimento, specificita' dell'ancora, scelta anticipata della foto alternativa (AUTO_ALT_PHOTO esiste gia'). Ogni regola ha interruttore, scadenza e ritorno automatico se, dopo l'applicazione, il tasso sulla stessa etichetta peggiora rispetto a prima.
NON puo': riscrivere il testo dei prompt. Un prompt cambiato in silenzio puo' introdurre affermazioni nuove; per la narrazione il ciclo produce una classifica delle regole che costano piu' tentativi e dei tipi di annuncio dove scattano, e la correzione alla fonte si fa con prova su lotti (non n=1) e senza peggiorare il controllo dei fatti.

## 8. Narrazione
Dati oggi in job_meta: modo (anchored, per_scene, testo unico), numero di tentativi, caratteristiche dell'annuncio. NON salvati: i motivi di rifiuto e il motivo del ripiego (fase 2). In fase 3 si propone anche una seconda lettura indipendente di ogni narrazione (Claude elenca ogni affermazione e se e' sostenuta dall'annuncio o dalle foto), in sola misura, per sapere quante affermazioni non sostenute superano il controllo euristico: costo da misurare, non stimato.

## 9. Rischi e limiti
- Poche scene: il ciclo puo' non trovare nulla per mesi; non e' un guasto.
- Etichette rumorose: nessuna regola vale su una sola etichetta.
- Seme da prove: stesse scene analizzate molte volte con varianti di prompt; contare ogni scena una sola volta.
- Rischio di rinforzare un errore: una regola che evita una combinazione la fa sparire dai dati; il controllo dopo l'applicazione deve guardare anche il tasso complessivo, non solo il sottogruppo.
- Non verificato: i nomi esatti dei campi di scena nel job_meta reale (anchor, anchor_side, depth, reflective_surface): il codice li legge in modo tollerante, ma la prima esecuzione sul server dira' quali mancano.
