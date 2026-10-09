# RELINX_QUESTIONS.md -- domande da concordare con Relinx (bozza 2026-10-09)

_Priorita: **P1** = serve prima della finestra di test (ultima settimana di ottobre); **P2** = prima del pilota GIAL; **P3** = prima dell'espansione. Ogni domanda e' collegata al rischio del piano di test (AUTOMATION_TEST_PLAN.md) che chiude. Le risposte vanno scritte nella colonna "Risposta" e riportate nel piano._

## A. Contratto API e dati in ingresso
| ID | Domanda | Perche' ci serve | Rischio | Prio | Risposta |
|---|---|---|---|---|---|
| Q-A1 | Potete inviarci lo schema completo della richiesta che inviate (campi, tipi, obbligatori/facoltativi, valori ammessi per `category`)? | Test di contratto e validazione; evitare rotture se cambiate un campo | F49, F17 | P1 | |
| Q-A2 | Oltre alla descrizione libera, potete inviare dati strutturati (mq, locali, piano, classe energetica, prezzo, extra come balcone/box/ascensore)? | Riduce il rischio che la narrazione inventi dettagli e permette di controllarla | F07 | P1 | |
| Q-A3 | Quante foto invia di norma un annuncio (minimo/massimo), in che formato e a che risoluzione? Mandate gli originali ad alta risoluzione o versioni ridotte dal portale? | Qualita' dell'immagine finale; soglia minima delle foto | F02, F16 | P1 | |
| Q-A4 | Le foto sono ordinate e categorizzate in modo affidabile (cucina, camera...)? Chi le categorizza? | Ordine delle scene e didascalie corrette | F17 | P1 | |
| Q-A5 | Gli URL firmati delle foto durano 3 giorni: se scadono prima che scarichiamo, potete rigenerarli? Possiamo scaricare subito alla richiesta? | Foto perse per scadenza | F03 | P1 | |
| Q-A6 | Il vostro client ha un timeout? Quanto, e ritenta in automatico? Quante volte? | Evitare doppioni come il 2 ottobre (4 tentativi) | F01 | P1 | |
| Q-A7 | In che lingua sono le descrizioni? Possono arrivare in altre lingue o con testo molto lungo/corto? | Casi limite della narrazione | F08, F50 | P2 | |
| Q-A8 | Posso avere una pianta dell'immobile quando c'e'? Indirizzo e nome dell'agenzia vanno pronunciati nel video o no? | Contenuto della narrazione e privacy | F07, F40 | P2 | |

## B. Come il video arriva e viene mostrato nel CRM
| ID | Domanda | Perche' ci serve | Rischio | Prio | Risposta |
|---|---|---|---|---|---|
| Q-B1 | Mostrate il video dal nostro indirizzo (streaming) oppure lo scaricate e lo ospitate voi? | Decide durata del link, banda, autenticazione | F35, F36 | P1 | |
| Q-B2 | Il `video_url` richiede la chiave partner: come lo riproduce il browser dell'agenzia? Serve un link firmato temporaneo che si apre senza chiave? Quanto deve durare? | Senza questo l'agenzia potrebbe non riuscire a vedere il video | F35 | P1 | |
| Q-B3 | Quali specifiche ha il vostro player: codec, dimensione massima del file, durata massima, orientamento (16:9, 9:16, 1:1), supporto a streaming progressivo? | Evitare file non riproducibili | F30, F37 | P1 | |
| Q-B4 | Servono altri formati o file: miniatura/poster, versione verticale per i social, sottotitoli? | Pianificare cosa generare | F30 | P2 | |
| Q-B5 | Quanto tempo deve restare disponibile il video per voi (30 giorni? per sempre)? Possiamo cancellarlo dopo? | Retention e spazio disco | F36, F21 | P2 | |
| Q-B6 | Possiamo provare un video nel vostro ambiente di test/staging con il vostro player prima della finestra? | Test di accettazione reale | F37 | P1 | |

## C. Webhook, stati e flusso
| ID | Domanda | Perche' ci serve | Rischio | Prio | Risposta |
|---|---|---|---|---|---|
| Q-C1 | Come verificate il webhook? Siete disposti a verificare una firma (HMAC) con un segreto condiviso? Come proteggete dai ripetuti? | Oggi la firma non e' attiva | F33 | P1 | |
| Q-C2 | Cosa si aspetta il vostro endpoint (risposta, tempo massimo)? Ritentate se rispondete errore? Quante volte e con quale intervallo? | Politica di ritentativo e consegna garantita | F32 | P1 | |
| Q-C3 | Ogni quanto leggete lo stato (`GET /v1/videos/{id}`)? Va bene che una richiesta resti in `in_review` fino a un giorno? | Carico e aspettative sui tempi | F10, F31 | P1 | |
| Q-C4 | Cosa mostra l'interfaccia all'agenzia per ogni stato (in coda, in revisione, in elaborazione, completato, errore)? In caso di errore, quale messaggio e quali azioni (riprova, annulla)? | Messaggi chiari e flusso di recupero | F32, F10 | P2 | |
| Q-C5 | Se l'annuncio cambia (foto, prezzo) dopo la richiesta, si deve rigenerare? Come lo segnalate? | Versioni e costi | F49 | P2 | |
| Q-C6 | Tempo di consegna atteso: quale e' accettabile per l'agenzia (ore)? Quale per il pilota? | Obiettivo R07 | F10 | P1 | |
| Q-C7 | Quante richieste al giorno prevedete nella finestra di test e nel pilota GIAL? Possono arrivare tutte insieme? | Dimensionamento e limite 2/24h | F22, F05 | P1 | |

## D. Qualita' e accettazione
| ID | Domanda | Perche' ci serve | Rischio | Prio | Risposta |
|---|---|---|---|---|---|
| Q-D1 | Come decidete che un video e' "soddisfacente"? Avete criteri o esempi di video che vi piacciono e che non vi piacciono? | Griglia di accettazione (QUALITY_CRITERIA.md) | F38 | P1 | |
| Q-D2 | Quali informazioni sono obbligatorie nella narrazione (tipologia, mq, locali, piano, extra, zona, classe energetica, prezzo)? E quali non devono mai essere dette (prezzo, indirizzo preciso, superlativi)? | Copertura dei contenuti, evitare affermazioni rischiose | F07 | P1 | |
| Q-D3 | Quale voce e tono preferite (maschile/femminile, energica, istituzionale)? Potete indicare 2-3 esempi? Va bene per tutte le agenzie? | Il feedback sul tono "da TG" | F19 | P1 | |
| Q-D4 | Durata ideale del video e numero di foto usate? | Ritmo e costo | F08 | P2 | |
| Q-D5 | Musica di sottofondo: si' o no? Se si', quali regole di licenza? | Cosa includere | F39 | P2 | |
| Q-D6 | Logo: ogni agenzia lo invia? In che formato? Se manca, cosa deve comparire (nulla, solo dicitura IA)? | Branding corretto | F18 | P1 | |
| Q-D7 | Persone, volti e targhe nelle foto: cosa fare (oscurare, scartare la foto, segnalare)? | Privacy | F40 | P1 | |
| Q-D8 | L'agenzia rivede il video prima di pubblicarlo sui portali? Dove sara' usato (portali, social, sito)? Servono specifiche per quei canali? | Contesto d'uso | F38 | P2 | |
| Q-D9 | Come raccogliamo il parere dell'agenzia: potete inoltrarci un riscontro (si pubblica cosi' / con modifiche / no, e il motivo) per ogni video? | KPI di accettazione e miglioramento | F38 | P1 | |
| Q-D10 | Come chiede l'agenzia una modifica (rifare una scena, cambiare voce)? Tramite voi? In quanto tempo? | Flusso di rework | F38, F24 | P2 | |

## E. Legale e privacy
| ID | Domanda | Perche' ci serve | Rischio | Prio | Risposta |
|---|---|---|---|---|---|
| Q-E1 | La liberatoria delle agenzie copre l'elaborazione delle foto con servizi IA di terzi, anche fuori dall'UE? Potete condividerne il testo? | GDPR, responsabili del trattamento | F40 | P1 | |
| Q-E2 | Serve un accordo di trattamento dati (DPA) tra noi e voi? Chi e' titolare e chi responsabile? | Conformita' | F40 | P1 | |
| Q-E3 | Sui video mettiamo solo la scritta "Generated with AI" (grigio chiaro, in basso a sinistra, nella lingua del video, niente logo nostro). Va bene? C'e' un obbligo o un testo preferito, anche per il CRM? | Etichetta IA | F39 | P1 | |
| Q-E4 | Per quanto conserviamo le foto originali e i video? Come gestiamo una richiesta di cancellazione? | Retention e diritto all'oblio | F36, F40 | P2 | |
| Q-E5 | Di chi e' la titolarita' dei video e delle foto, e possiamo usarli come esempi (anonimizzati)? | Uso dei contenuti | F39 | P3 | |

## F. Finestra di test e pilota
| ID | Domanda | Perche' ci serve | Rischio | Prio | Risposta |
|---|---|---|---|---|---|
| Q-F1 | Chi e' il referente tecnico e chi quello di prodotto da parte vostra? Con quale orario di reperibilita' durante la finestra? | Escalation rapida | F44 | P1 | |
| Q-F2 | Date esatte della finestra (2-3 giorni, ultima settimana di ottobre) e fascia oraria in cui inviate le richieste. | Pianificazione operatore | F44 | P1 | |
| Q-F3 | Potete usare un `callback_url` di test separato e un ambiente in cui non si notifichino gli utenti finali? | Evitare di contaminare la produzione | F46 | P1 | |
| Q-F4 | Potete fornirci annunci reali da piu' agenzie (circa 30, di cui circa 10 difficili) per il test interno prima della finestra? Quali casi difficili conoscete (foto scure, poche foto, testi lunghi)? | Fase 1 del piano | F50 | P1 | |
| Q-F8 | Nella fase interna possiamo coinvolgere il vostro referente (Michele) come secondo revisore dei video, con una griglia comune? Quanto tempo puo' dedicare? | Secondo sguardo indipendente prima del pilota | F53 | P1 | |
| Q-F5 | Accettate i criteri di successo proposti (>=95% completati senza intervento sul server, 0 doppioni, tempi concordati, accettazione >= 90%)? | Criteri di uscita condivisi | tutti | P1 | |
| Q-F6 | Cosa succede se un video non e' pronto in tempo o fallisce? Come lo comunicate all'agenzia durante il pilota? | Aspettative del pilota | F10, F32 | P2 | |
| Q-F7 | Per la fase successiva: avete requisiti di continuita' del servizio (orari, tempi di risposta ai problemi)? | Impegni di servizio | F41, F44 | P3 | |

## G. Commerciale (da trattare a voce, non in questo elenco)
Prezzo annuale a scaglioni, ruolo di Relinx nella fatturazione e margine: gia' in discussione separata. Non inserirlo nell'email tecnica.
