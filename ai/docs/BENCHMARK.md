# Quanto conta bene la visione — benchmark dell'11/10/2026

Numeri della UNO Q con le impostazioni dall'11/10 mattina (`profiles.unoq` in `ai/config.yaml`), su video veri
ripresi da camere ferme, confrontati con un riferimento controllato a vista. Rifarli: sezione "Come si rifà".

## In breve, per tutti

Su 8 video con la camera ferma (Torino di giorno e di notte, una zona pedonale, un piazzale, una strada):

| | Passaggi veri | Contati dalla scheda | Nel verso giusto | Conteggi in più |
|---|---:|---:|---:|---:|
| **Pedoni** | 23 | **13 (57%)** | 13 su 13 (100%) | 0 |
| **Ciclisti** | 4 | **2 (50%)** | 2 su 2 (100%) | 0 |
| **Veicoli** | 77 | **47 (61%)** | 47 su 47 (100%) | 0 |

- **Quando la scheda conta un passaggio, è vero e ha il verso giusto**: 0 conteggi falsi o doppi e verso giusto
  nel 100% dei casi, di giorno e di notte.
- **Dove la camera vede bene la linea** (notte a Torino, zona pedonale, piazzale, strada): **17 passaggi su 17**.
- **Dove la scheda ne perde**: nei video di Torino ripresi da un balcone, dove un palo della luce copre proprio il
  punto in cui si attraversa e le persone sulle strisce lontane sono alte 15 pixel. Lì conta 45 passaggi su 87.
  Con la camera montata sul semaforo, sopra le strisce, nessuna delle due cose succede.
- **Prima delle correzioni di oggi** gli stessi video davano: pedoni 9 su 23 (39%), ciclisti 0 su 4, veicoli
  24 su 77 (31%). **Persone contate: da 9 a 15 su 27; veicoli: da 24 a 47 su 77.**
- La scheda analizza **5,9 fotogrammi al secondo**, tutti con il detector (prima 8,4, ma solo 4,2 analizzati: gli
  altri ripetevano le posizioni precedenti). Tutto in locale, nessun fotogramma salvato.

## Come è fatto il confronto

1. **Riferimento**: lo stesso programma con un detector molto più grande (YOLOX-l a 960 px, circa 500 volte i calcoli
   di quello della scheda) su ogni fotogramma a 15 FPS, sul Mac. Un passaggio vale solo se l'oggetto resta 0,5 s oltre
   la linea, come sulla scheda (`benchmark.py run riferimento`, `reference`).
2. **Scheda**: il programma della scheda sul Mac con i limiti della scheda (`--emulate-unoq`: 320 px, 4 thread) e
   gli **FPS misurati sulla scheda vera** l'11/10: 8,4 FPS con il detector un fotogramma su due, 5,9 con il detector
   su ogni fotogramma, 3,8 a 416 px.
3. **Accoppiamento**: un passaggio contato dalla scheda e uno del riferimento sono lo stesso se sono sulla stessa
   linea, dello stesso tipo, entro 2 s e 120 px dal punto in cui l'oggetto supera la linea (`smartcrossing/scoring.py`,
   provato in `tests/test_scoring.py`). Pedone e ciclista si possono accoppiare: due modelli spesso non concordano su
   chi pedala.
4. **Revisione a vista**: per ogni disaccordo un foglio con l'oggetto 1 s prima, sulla linea e 1 s dopo
   (`benchmark.py review`). Dove aveva ragione la scheda il riferimento è corretto e annotato
   (`benchmark.py judge`, campo `review` di `benchmarks/reference/<video>.json`). Controllati tutti i disaccordi sui
   pedoni e un campione di quelli sui veicoli: 2 passaggi veri erano sfuggiti al riferimento (aggiunti), nessun
   passaggio del riferimento era falso.
5. **Solo camere ferme**: 5 dei 13 video di prova (NYC ×2, Shibuya, Mixkit 4194 e 4335) sono time-lapse o ripresi a
   mano: la differenza media tra un fotogramma e il successivo è 15–18 su 255, contro 1–4 delle camere ferme. Una linea
   disegnata sull'immagine lì non resta sulla strada, quindi non valgono per il conteggio (`"fixed": false` in
   `benchmarks/videos.json`; con `score --moving` si vedono lo stesso: pedoni da 9 a 22 su 48, veicoli da 24 a 48
   su 87).

## Cosa è cambiato e quanto ha reso

Ogni riga aggiunge una modifica alla precedente (camere ferme; pedoni / veicoli contati):

| Modifica | Pedoni | Veicoli |
|---|---:|---:|
| Prima (8,4 FPS, detector un fotogramma su due, tracking di supervision) | 9 / 23 | 24 / 77 |
| Tracce restituite con il box giusto + box allargati del 30% + lato della linea ricordato | 10 / 23 | 32 / 77 |
| Detector su ogni fotogramma (5,9 FPS, tutti analizzati) | 13 / 23 | 44 / 77 |
| Box allargati del 50% invece del 30% — **configurazione adottata** | **13 / 23** | **47 / 77** |

Le tre correzioni del tracking (`smartcrossing/tracking.py`, `counting.py`):

- **Tracce perse all'uscita di ByteTrack.** supervision restituiva una traccia solo se la sua posizione filtrata
  (Kalman) copriva il box del detector per più del 50%. Con 4–6 rilevamenti al secondo la posizione filtrata di
  un'auto resta indietro: l'auto era seguita ma non restituita, e quindi mai contata (ecco i "0 veicoli nel verso
  lontano" del punto 42 di `DECISIONS.md`). Ora ogni traccia esce con il box con cui è stata associata.
- **Box allargati per l'associazione** (buffered IoU, dal tracker C-BIoU, Yang et al., WACV 2023): tra due
  rilevamenti un'auto si sposta di quasi la sua lunghezza e due box consecutivi non si sovrappongono più. Il tracker
  li confronta allargati del 50% per lato e restituisce quelli veri. Costo: qualche moltiplicazione per box.
- **Lato della linea ricordato.** `sv.LineZone` dimenticava da che parte stava un oggetto dopo 4 rilevamenti senza
  vederlo (un'auto dietro un palo): ora lo ricorda per 30 rilevamenti, quanto ByteTrack tiene una traccia persa.

Il benchmark stesso è stato corretto: si confronta il punto e l'istante in cui l'oggetto supera la linea, non quelli
della conferma (che arriva 3 rilevamenti dopo, a 4 al secondo 0,7 s e 150 px più in là: prima auto contate risultavano
perse); il riferimento conferma dopo 0,5 s come la scheda (a 30 FPS con 3 fotogrammi = 0,1 s contava due volte chi
cammina sulla linea); i video si analizzano agli FPS esatti della scheda (8,4 FPS di un video a 30 erano 7,5).

## Provato e non adottato

| Tecnica | Risultato | Perché no |
|---|---|---|
| Detector a 416 px (su ogni fotogramma) | pedoni 13/23, veicoli 40/77 | la scheda scende a 3,8 FPS: vede meglio i piccoli ma perde gli oggetti veloci |
| Nuove tracce da punteggio 0,30 invece di 0,40 | pedoni uguali, veicoli 46/77 (−1) | 1 conteggio in più; insieme alla ricucitura 49/77 ma più doppioni nei video affollati |
| Conferma dopo 2 rilevamenti invece di 3 | uguale | nessun guadagno, più rischio di doppioni |
| Ricucitura delle tracce attraverso la linea (`counting.stitch_s`) | veicoli +1 | +1 conteggio in più; nelle folle collega persone diverse. Resta nel codice, spenta |
| Modello a 8 bit (INT8) | stessi oggetti del modello normale | sulla scheda più lento (283 ms contro 208–230): il Cortex-A53 non ha istruzioni int8 (punto 45) |
| PP-PicoDet-S (detector più recente) | +36% di persone trovate | 2,2 volte più lento sulla scheda (punto 46) |
| Correzione gamma di notte | — | non serve: il video notturno ha la stessa luminosità media di quelli di giorno (125 su 255) |

## Limiti e prossimi passi

- **Pochi passaggi**: 27 persone e 77 veicoli. I numeri danno l'ordine di grandezza, non la seconda cifra. Torino_4
  (220 s, molte persone sulle strisce) e Torino_7 hanno inquadrature diverse da Torino_3 e Torino_1: con una
  calibrazione ciascuno il campione raddoppia.
- **Persone piccole**: sotto i 20 px di altezza YOLOX-nano a 320 px le perde. Rimedio vero: camera più vicina alle
  strisce (sul semaforo), oppure restringere l'area analizzata (`roi` della calibrazione) alle strisce e all'attesa.
- **Camera vera**: rifare il benchmark con 2–3 minuti ripresi dalla camera della scheda montata, appena è fissata.
- Le varianti e tutti i numeri per video: `benchmarks/variants.json`, `benchmarks/results/<variante>.json`.

## Come si rifà

```bash
cd ai
python scripts/benchmark.py run riferimento        # sul Mac, ~40 min (CoreML); poi:
python scripts/benchmark.py reference              # passaggi del riferimento in benchmarks/reference/
python scripts/benchmark.py run scheda_nuova       # ~1 min per variante
python scripts/benchmark.py score scheda_prima scheda_nuova
python scripts/benchmark.py review scheda_nuova torino_1   # fogli dei disaccordi in samples/report/review/
python scripts/benchmark.py judge scheda_nuova torino_1 --add g3 --note "..."   # dopo averli guardati
```

Un solo `judge` per video con tutte le decisioni, poi di nuovo `review`: dopo ogni `judge` i numeri `r…`/`g…` dei
fogli cambiano. I video stanno in `ai/samples/` (fuori da git). Se macOS ne blocca la lettura ("Operation not permitted"), copiarli
dalla scheda e indicare la cartella con `MDGB_VIDEOS=<cartella>`.
