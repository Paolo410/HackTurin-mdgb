# Logo MDGB

Logo di MDGB (Mobility Data & Guardian Beacon). Per vederlo dove viene usato e confrontarlo con le altre proposte
apri [`proposte.html`](proposte.html) nel browser (funziona senza rete).

**"Telecamera intelligente":** una telecamera da strada sul suo braccio, che guarda in basso verso
l'attraversamento. La lente è il faro ambra; gli archi davanti dicono che vede e avvisa. Il nome MDGB è disegnato
insieme al simbolo, non scritto con un font: è uguale su ogni computer.

## File

| File | Per cosa |
|---|---|
| `mdgb-simbolo.svg` | simbolo da solo: la telecamera (favicon, intestazioni, misure piccole) |
| `mdgb-icona.svg` | simbolo con il nome sotto la telecamera (icona dell'app, avatar), da 48 px in su |
| `mdgb-logo.svg` | simbolo e nome, per sfondi chiari |
| `mdgb-logo-scuro.svg` | simbolo e nome, per sfondi scuri (video, mappa scura) |
| `mappa/pin-ok.svg`, `pin-rete-giu.svg`, `pin-guasto.svg`, `pin-senza-dati.svg` | spilli della mappa della centrale, con i colori di stato di `app/` (punta a x 24, y 62 del disegno 48×64) |
| `trailer/mdgb-cartello-16x9.svg` | cartello del trailer, 1920×1080 |
| `alternative/` | le proposte scartate: strisce e faro (il logo di prima), scudo, occhio, lanterna |
| `genera_logo.py` | riscrive tutti i file del logo da un solo disegno |

Lo script riscrive anche le copie del simbolo che stanno dentro altri file, perché quando girano non possono
leggere questa cartella:

| Copia | Dove si vede |
|---|---|
| `../../ai/smartcrossing/brand.py` | pagina del tecnico della visione (logo e favicon) |
| `../../app/dashboard.html` (il solo `<svg>` dell'intestazione) | dashboard della centrale |
| `../../firmware/unoq_mcu/assets/logo.svg` | pannello dell'app App Lab (barra e icona) |

L'icona dell'app della centrale non è un file: la disegna `app/desktop/make_icon.py` a ogni build, leggendo le
forme da `genera_logo.py`.

Per cambiare un colore o il disegno: modifica `genera_logo.py` (le misure della telecamera e delle lettere sono
in cima), lancia `python docs/brand/genera_logo.py` e committa tutto quello che ha riscritto. Poi vanno rifatte
la build dell'app della centrale e la copia sulla scheda di visione e app App Lab.

## Colori

| Nome | Codice | Uso |
|---|---|---|
| Asfalto | `#1d2226` | fondo del simbolo, testi |
| Bianco cartello | `#f3f4f1` | la telecamera, il nome su fondo scuro, sfondi chiari |
| Faro ambra | `#f2a900` | la lente, gli archi, gli accenti |
| Verde / rosso | `#3fbf6a` / `#e5483f` | stati (ok / guasto) |
| Blu cartello | `#1f5fae` | link e informazioni |

## Regole minime

- Spazio libero intorno al simbolo: almeno un quarto della sua larghezza.
- Sotto i 48 px usa il simbolo senza nome (`mdgb-simbolo.svg`): le lettere non si leggerebbero.
- Il nome è disegnato: non riscriverlo con un font. Solo la riga "Mobility Data & Guardian Beacon" usa i font di
  sistema: per stampa e video riscrivila nel font scelto per il trailer.
- Non deformare, non ruotare, non cambiare i colori della telecamera e della lente.
