# MDGB — The time you need · English narration and on-screen text

Cinematic English adaptation of the animatic's Italian voice-over (`Trailer MDGB.html`) and of the GOMA brief read at the kickoff (`docs/Transcription.txt`).
Generated from `timeline.json`, which is the source of truth: edit the timeline, then `python tools/build.py`.

| Scene | Time | Narration (EN) | Original (IT) |
|---|---|---|---|
| B01 The duel | 0:00 | — (music, ticking signal) | — |
| B02 The math | 0:06 | She needs ten seconds to cross. The car arrives in four. And the traffic light has no idea. | Le servono dieci secondi per attraversare. L'auto arriva tra quattro. Un semaforo normale non lo sa. |
| B03 The data | 0:12 | Detecting presence isn't enough. You have to understand the scene. | GOMA brief: «Rilevare la presenza non basta, occorre interpretare la scena» |
| B04 Darkness | 0:20 | On October twenty-fifth, darkness falls at rush hour. And the green light lasts the same... for someone who's twenty, and for someone who's eighty. | Dal 25 ottobre il buio arriva all'ora di punta. E il verde dura uguale per chi ha vent'anni e per chi ne ha ottanta. |
| B05 MDGB | 0:30 | This is MDGB. | Questo è MDGB. |
| B06 On the light that's already there | 0:37 | Two hundred euros of hardware, on the traffic light that's already there. It sees who's coming — and asks for the time they need. | Un modulo da circa duecento euro, sul semaforo che c'è già. Vede chi arriva. E chiede il tempo che serve. |
| B07 It sees | 0:46 | Pedestrians. Cyclists. Cars. Animals. All recognised on board. No internet. | Riconosce pedoni, ciclisti, auto e animali. Tutto a bordo. Senza internet. |
| B08 It measures | 0:54 | The stripes are its ruler: fifty centimetres, every time. That's how it measures real distance... and real speed. | Le strisce sono il suo metro: cinquanta centimetri, sempre. Così misura distanze e velocità vere. |
| B09 It understands | 1:01 | It doesn't guess your age. It measures your pace. Walk slowly — and it waits for you. | Non indovina l'età. Misura il passo. Se cammini piano, ti aspetta. |
| B10 It decides and acts | 1:10 | Every decision follows a physical rule — written down, verifiable. It warns the driver. Holds the red. Extends the green. | Ogni decisione è una regola fisica, scritta e verificabile. Avvisa chi guida. Trattiene il rosso. Allunga il verde. |
| B11 Fail-safe | 1:18 | And if the AI goes dark? In half a second, the light is back exactly as it was. | E se l'intelligenza artificiale si spegne? In mezzo secondo il semaforo torna esattamente com'era. |
| B12 Loses nothing | 1:25 | If the network drops, it switches to Bluetooth. When it's back, it recovers everything. Events lost: zero. | Se cade la rete, passa al Bluetooth. Quando torna, recupera tutto. Eventi persi: zero. |
| B13 No faces | 1:34 | It never stores an image. Ever. Only anonymous numbers. At night, it senses heat — but recognises no one. | Non salva immagini. Mai. Solo numeri anonimi. Di notte sente il calore, ma non riconosce nessuno. |
| B14 The city | 1:42 | One crossing protects. A hundred crossings reveal a city — its flows, its weather, its air. And where more time will be needed. | Un incrocio protegge chi passa. Cento incroci raccontano la città: flussi, meteo, aria. Per prevedere dove servirà più tempo. |
| B15 The time you need | 1:52 | MDGB. The time you need. | MDGB. Il tempo che serve. |

## On-screen text

- **B01 The duel**: 9.8 s · TO CROSS · 4.3 s · UNTIL THE CAR ARRIVES
- **B02 The math**: 4.3 s · 9.8 s · < · CAR ARRIVES · SHE NEEDS
- **B03 The data**: 470 · pedestrians killed on Italian roads in 2024 · More than one every single day. · Source: ACI–ISTAT, road accidents 2024
- **B04 Darkness**: OCTOBER 25 · Clocks go back. Darkness at rush hour. · 17:30
- **B05 MDGB**: MDGB · Mobility Data & Guardian Beacon
- **B06 On the light that's already there**: MDGB NODE · ~€200 in parts / Fits existing traffic lights · TURIN
- **B07 It sees**: CAM 01 / ON-BOARD AI / WI-FI OFF · SEES
- **B08 It measures**: 50 cm + 50 cm = 1 m · W = 7.0 m · MEASURES
- **B09 It understands**: UNDERSTANDS
- **B10 It decides and acts**: TTC = d / v = 4.3 s / T_need = W / v_ped + 1 = 9.8 s / 4.3 s < 9.8 s  →  WARN_DRIVER · PEDESTRIAN  50 km/h / SLOW DOWN · WAIT · BRAKE! · DECIDES
- **B11 Fail-safe**: HEARTBEAT · 100 ms · VISION OFFLINE · FAIL-SAFE · 0.5 s · BACK TO THE NORMAL CYCLE · FAILS SAFE
- **B12 Loses nothing**: WI-FI ✕ · BLUETOOTH BEACON · 27 BYTES · WI-FI ✓ · QUEUE FLUSHED · EVENTS LOST · LOSES NOTHING
- **B13 No faces**: 0 FRAMES STORED · METADATA ONLY · SEES NO FACES
- **B14 The city**: TOMORROW · 18:00 / RAIN · +38% FOOT TRAFFIC / 12 CROSSINGS NEED MORE TIME · CONCEPT · SIMULATED DATA
- **B15 The time you need**: CROSSINGS TODAY · MDGB · The time you need. · HackTurin 2026 · GOMA Smart Crossing Challenge · Paolo Malugani – AI & vision / Salvatore Gullotta – firmware / Lorenzo Dragoni – network & control room / Kuzey Bicher – electronics

## Voice

Kokoro TTS (offline), blend `am_michael:0.65,am_onyx:0.35`, speed 0.9, +0.5 semitone of depth, EQ, compression, small room. Credited as a synthetic voice.
