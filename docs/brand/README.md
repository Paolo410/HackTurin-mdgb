# Logo MDGB (segnaposto)

Logo provvisorio di MDGB (Mobility Data & Guardian Beacon), da usare finché non ce n'è uno definitivo.
Per confrontare le proposte apri [`proposte.html`](proposte.html) nel browser (funziona senza rete).

**Proposta principale, "strisce e faro":** la M di MDGB tagliata da cinque bande orizzontali, come le strisce
pedonali viste dall'auto; il faro ambra nella punta della M veglia sull'attraversamento.

## File

| File | Per cosa |
|---|---|
| `mdgb-simbolo.svg` | simbolo da solo (icona, favicon, avatar); già dentro la pagina del tecnico |
| `mdgb-logo.svg` | simbolo e nome, per sfondi chiari |
| `mdgb-logo-scuro.svg` | simbolo e nome, per sfondi scuri (video, mappa scura) |
| `mappa/pin-ok.svg`, `pin-rete-giu.svg`, `pin-guasto.svg`, `pin-senza-dati.svg` | spilli della mappa della centrale, con i colori di stato di `app/` (punta a x 24, y 62 del disegno 48×64) |
| `trailer/mdgb-cartello-16x9.svg` | cartello del trailer, 1920×1080 |
| `alternative/` | tre proposte alternative: scudo, occhio, lanterna (disegnate a mano) |
| `genera_logo.py` | rigenera tutti i file della proposta principale da un solo disegno |

Per cambiare un colore o il disegno: modifica `genera_logo.py`, poi `python docs/brand/genera_logo.py`, e committa
gli SVG. Ricorda di aggiornare anche il logo dentro `ai/smartcrossing/operator_ui.py` (stesso disegno).

## Colori

| Nome | Codice | Uso |
|---|---|---|
| Asfalto | `#1d2226` | fondo del simbolo, testi |
| Bianco cartello | `#f3f4f1` | strisce, sfondi chiari |
| Faro ambra | `#f2a900` | il faro, gli accenti |
| Verde / rosso | `#3fbf6a` / `#e5483f` | stati (ok / guasto) |
| Blu cartello | `#1f5fae` | link e informazioni |

## Regole minime

- Spazio libero intorno al simbolo: almeno un quarto della sua larghezza.
- Sotto i 16 px usa solo il simbolo, senza nome.
- Il nome usa i font di sistema: per stampa e video riscrivilo nel font scelto per il trailer.
- Non deformare, non ruotare, non cambiare i colori del faro e delle strisce.
