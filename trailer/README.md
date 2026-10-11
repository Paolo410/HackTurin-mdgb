# Trailer MDGB — Proof of Concept (EN)

Trailer di 2:00 in inglese per MDGB (HackTurin 2026, sfida GOMA Smart Crossing), costruito come codice:
la timeline è un file JSON, le grafiche sono componenti React (Remotion), audio e montaggio sono FFmpeg/Python.
Le riprese sono **stock provvisorie** (Pexels): si sostituiscono con le vostre cambiando una riga.

Output: `output/MDGB_trailer_PoC_v1.mp4` (1920×1080, 30 fps, H.264 + AAC, −14 LUFS) e `output/MDGB_trailer_PoC_v1.en.srt`.

## Struttura

```
trailer/
├── timeline.json          ← IL MONTAGGIO: 15 scene, inquadrature, voce, testi a schermo, musica, effetti
├── media.json             ← registro clip: file, autore, pagina, licenza (crediti)
├── script/narration_en.md ← narrazione EN scena per scena, con l'originale IT dell'animatic
├── assets/b-roll/         ← clip stock scaricate (git-ignored)
├── assets/music/          ← brano (git-ignored)
├── tools/                 ← pipeline Python
│   ├── build.py           ← un comando per tutto
│   ├── fetch_broll.py     ← ricerca/download Pexels, Pixabay, Wikimedia Commons
│   ├── prep_media.py      ← FFmpeg: conform 1080p30, trim, freeze-frame, ingest
│   ├── tts.py             ← voce narrante EN (Kokoro offline / Edge / ElevenLabs / OpenAI)
│   ├── beats.py           ← griglia dei battiti, tagli agganciati al beat
│   ├── mix.py + sfx.py    ← montaggio musicale, ducking sotto la voce, effetti, master −14 LUFS
│   └── detect.py          ← riquadri VERI con il detector del team (ai/smartcrossing, YOLOX + ByteTrack)
├── motion/                ← progetto Remotion (grafiche e composizione)
│   └── src/scenes/        ← open (B01–B04) · reveal (B05–B06) · proof (B07–B13) · close (B14–B15)
├── skills/               ← le 5 skill per gli agenti (scraper, ffmpeg, motion, tts, ducking/sync)
├── build/                 ← intermedi (git-ignored)
└── output/                ← video finali (git-ignored)
```

## Skill per gli agenti

Le 5 skill (`skills/<nome>/SKILL.md`) descrivono come un agente usa questa pipeline. Per attivarle in
Claude Code dentro `trailer/` (gli strumenti remoti non possono scrivere in `.claude/`):
```bash
mkdir -p trailer/.claude && cp -R trailer/skills trailer/.claude/skills
```

## Setup (una volta, sul Mac)

```bash
bash trailer/setup.sh          # ffmpeg/node via brew se mancano, venv Python, modelli (Kokoro, YOLOX), npm install
```
Chiavi (solo se servono): copiare `.env.example` in `.env` → `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `ELEVENLABS_API_KEY`, `OPENAI_API_KEY`.

## Rigenerare il video

```bash
cd trailer
.venv/bin/python tools/build.py                 # tutto: media → beats → voice → mix → detect → data → render → mux
.venv/bin/python tools/build.py data render mux # dopo aver cambiato testi o grafiche
.venv/bin/python tools/build.py voice mix mux   # dopo aver cambiato la narrazione
```
Anteprima interattiva delle grafiche: `cd motion && npm run studio`.

## Sostituire le clip stock con le vostre

1. Mettete il file in `assets/own/` (es. `D1_zenitale.mp4`).
2. In `media.json` cambiate `file` della clip da sostituire (es. `c01_crosswalk_aerial_a` → `assets/own/D1_zenitale.mp4`)
   oppure: `.venv/bin/python tools/prep_media.py --ingest assets/own/D1_zenitale.mp4 c01_crosswalk_aerial_a`.
3. Se serve, regolate `in` / `dur` dell'inquadratura in `timeline.json`.
4. Per le scene con riquadri (B01, B07, B09, B13) cancellate `build/public/data/detections_<clip>.json`:
   il passo `detect` li rifà con il vostro detector sulla nuova ripresa.
5. `.venv/bin/python tools/build.py media detect data render mux`.

| Scena | Clip stock ora | Ripresa del piano originale |
|---|---|---|
| B01–B02, B15 | c01 / c02 aerea strisce | D1 zenitale |
| B03 | c03–c10 montaggio | S2 dettagli, D4 tram |
| B04 | c26 Torino + c12 notte | S3 sera finta, D2/D3 |
| B05 | c13 obiettivo, c14 PCB | P1 il modulo |
| B06 | c15 Mole tilt-shift, c16 semaforo | D5 + P2 plastico |
| B07 | c17 vista dal palo | S1 + SC1 overlay |
| B08 | c18 strisce | SC2 calibrazione |
| B09 | c19–c21 | S1, P6 figurine |
| B10 | c05, c22 | SC3 + P3 LCD/OLED veri |
| B11 | c23 semaforo | P4 kill test |
| B12 | c24 cavi | SC4 centrale Wi-Fi/BLE |
| B13 | c25 folla dall'alto | S1 + termocamera |
| B14 | c26 Torino | D3 + centrale |

## Note oneste (da sistemare prima della versione finale)

- Numeri a schermo: tutti dal piano del trailer e dal repo; B14 è etichettata «concept · simulated data».
- I riquadri di B07/B09/B13 sono rilevamenti veri del detector del team, ma su clip stock: non sono prove sul campo.
- Voce sintetica (Kokoro TTS, offline) dichiarata nei titoli di coda; si può sostituire riga per riga
  con una registrazione (`build/audio/vo/L05.wav` ecc., 48 kHz mono) e `tools/build.py mix mux`.
- Musica: «Epic Trailer» di The_Mountain (Pixabay, licenza Pixabay, senza Content ID). Clip: licenza Pexels, autori in `media.json`.
- Remotion è gratuito per individui e team piccoli: per usi commerciali verificate remotion.dev/license.
