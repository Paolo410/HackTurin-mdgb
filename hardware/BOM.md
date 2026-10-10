# BOM — Smart Crossing (sfida GOMA)

Owner: electronics engineer. Basata sul file `docs/Materiale di elettronica da reperire.xlsx`
(colonne: **Kit** = già nel kit del team · **Inv** = inventario condiviso da richiedere).
Serve a tre cose:
1. chiedere i componenti e sapere cosa manca;
2. avere i costi per il pitch (dispositivo da circa 150–250€ contro i circa 16.700€ ad attraversamento spesi a Como);
3. fare da riferimento per cablaggio e pinout (la sezione Pinout sta in `docs/CONTRACTS.md`).

Priorità: **P1** = indispensabile per la demo · **P2** = molto utile · **P3** = solo se avanza tempo.

## Da richiedere (tutto disponibile nella lista)

| Componente | Fonte | Qtà | Uso | Priorità |
|---|---|---|---|---|
| Arduino UNO Q 4 GB | Kit | 1 | Cervello: visione su Linux, sicurezza sul MCU | P1 |
| Arduino UNO Media Carrier | Inv | 1 | Porte CSI per le camere. **Verificare subito il supporto IMX219** | P1 |
| Camera Sony IMX219 8MP | Inv | 2 | 1 sulle strisce + 1 di ricambio (o sulla corsia d'arrivo a FPS ridotti) | P1 |
| Grove Base Shield V2 | Inv | 1 | **Interruttore su 3,3 V** (logica UNO Q a 3,3 V: verificare) | P1 |
| Cavi Grove 4 pin 20 cm / jumper→Grove / 5 cm | Inv | 6 / 4 / 2 | Cablaggio dei moduli Grove | P1 |
| Breadboard / millefori | Inv | 2 / 1 | Prototipo, poi montaggio saldato per la demo | P1 |
| Jumper M-M, F-F, M-F | Kit | 10+10+10 | — | P1 |
| **Grove WS2813 RGB LED Strip 1 m (30 LED)** | Inv | 2 | **Segnalazione visibile**: 1 = ambra/rosso verso i veicoli, 1 = rosso a terra per i pedoni. Alimentazione 5 V esterna (vedi note) | P1 |
| **Grove RGB LED Ring (16 WS2813)** | Inv | 1 | "Lanterna" pedonale sul palo + giallo di fail-safe | P1 |
| Grove Passive Buzzer | Inv | 1 | Avviso sonoro WARN_PEDESTRIAN | P1 |
| Grove Light Sensor | Inv | 1 | Modalità notte + luminosità adattiva dei LED | P1 |
| Grove AHT20 (temperatura/umidità) | Inv | 1 | Correlazione flussi ↔ meteo negli aggregati + rischio di lente appannata | P2 |
| Resistenze + condensatori | Inv | qualche pezzo | 330 Ω in serie sul segnale dati della strip, condensatore elettrolitico ~1000 µF sull'alimentazione della strip | P1 |
| Modulo USB-C (breakout) | Inv | 2 | Alimentazione 5 V separata per le strip LED | P1 |
| Grove 16x2 LCD | Inv | 1 | Display verso i conducenti: "PEDONE 47 km/h" / "ANIMALI IN STRADA" (al posto della matrice LED, che non c'è) | P2 |
| Grove OLED 0,96" | Inv | 1 | Display verso i pedoni: conto alla rovescia, "ATTENDI: auto a 45 km/h" | P2 |
| **Grove Digital PIR** | Inv | 1 | Presenza in zona d'attesa **indipendente dalla visione** (funziona al buio), letta dal MCU → test con la camera staccata | P2 |
| **Modulino Distance** (ToF, circa 1,3 m) | Kit | 1 | Presenza ravvicinata al palo / pulsante "senza contatto". Anche questo va al MCU: secondo percorso di sicurezza | P2 |
| **Grove Thermal Imaging Camera (MLX90621, 16x4, 60°)** | Inv | 1 | Striscia di calore lungo il cordolo: presenza notturna per zona (a 4 m ogni colonna copre circa 29 cm). **Non** fa classificazione | P2 |
| **Grove 2.5A DC Current Sensor (ACS70331)** | Inv | 1 | **Monitoraggio della lampada**: verifica che i LED si accendano davvero (corrente attesa vs misurata). Se c'è un guasto → DEGRADED + allarme manutenzione. Argomento "safety" per GOMA | P2 |
| Modulino Movement (IMU) | Kit | 1 | Palo urtato o camera spostata → calibrazione non valida → DEGRADED + evento | P2 |
| Grove Touch Sensor | Inv | 1 | Pulsante di chiamata pedonale **accessibile** (non serve forza) | P2 |
| Grove Magnetic Switch | Inv | 1 | Sensore di apertura del case (manomissione) | P2 |
| Grove Coulomb Counter | Inv | 1 | Misura il consumo reale → numeri per la slide sull'energia | P2 |
| Grove MP3 Module V4 | Inv | 1 | Messaggi vocali per ipovedenti ("Attendere, veicolo in arrivo"). Verificare se l'altoparlante è incluso | P3 |
| Potenziometro | Kit | 1 | Manopola della demo: simula la velocità del veicolo sul plastico (o regola W dal vivo) | P3 |
| LiPo 1000 mAh + Waveshare Solar Charger + Mini Solar Panel | Inv | 1+1+1 | Solo **batteria tampone** (vedi bilancio energetico) | P3 |
| Grove Sound Sensor | Inv | 1 | Conferma degli incidenti (picco sonoro + regola sulle traiettorie) | P3 |
| Cartoncino, bastoncini, elastici, magneti + stampanti 3D | Inv | q.b. | **Plastico** dell'attraversamento + case + supporto della camera | P1 |

## Dalla BOM precedente: cosa cambia

| Prima | Ora | Motivo |
|---|---|---|
| LED 3 mm/5 mm come segnalazione | WS2813 strip + LED Ring | Disponibili e visibili |
| Matrice LED 8x32 | Grove LCD 16x2 | La matrice non è in lista |
| Radar HLK-LD2450 | PIR + Modulino Distance | Il radar non è in lista. Restano due sensori **non visivi** collegati al MCU per il fail-safe |
| MLX90640 (32x24) | MLX90621 (16x4) | In lista c'è solo la 16x4: presenza per zona, niente classificazione |
| Micro switch ×2 | Touch (chiamata) + Magnetic switch (case) | Più adatti allo scopo |
| NFC PN532 | Tolto | Non porta punti (l'AHT20 resta, per la correlazione con il meteo) |
| XIAO ESP32 per V2X | Tolto | Il "cruscotto auto" è uno **smartphone** che riceve via Wi-Fi/BLE dalla UNO Q |
| (nuovo) | ACS70331 per il monitoraggio della lampada | Chiude il cerchio della sicurezza: comando → LED acceso verificato |

Da non richiedere: SGP30/SGP41, RFID 125 kHz, servo, relè, elettromagnete, sensori Hall/tilt/vibrazione/piezo
(il Modulino Movement li copre), FSR, encoder, joystick, ricevitore IR.

## Non in lista: da portare da casa o da chiedere

| Cosa | Perché | Priorità |
|---|---|---|
| **Webcam USB** (+ hub USB-C se serve) | Piano B se l'IMX219 non funziona sulla Media Carrier. Senza, si resta **senza visione** | P1 |
| 2 caricatori USB-C 5 V/3 A + power bank | Alimentazione della UNO Q e delle strip LED | P1 |
| Treppiede o asta (2–3 m) | Inquadratura dall'alto per i test su strada; per il plastico basta un supporto stampato | P1 |
| Smartphone | "Cruscotto auto" per la demo V2X e dashboard | P2 |

## Note tecniche

- **WS2813 e alimentazione**: 30 LED a pieno bianco assorbono fino a circa 1,8 A. Limitate la luminosità via software
  (circa 30% → circa 0,5 A) e alimentate le strip da un 5 V separato, con la massa in comune con la UNO Q.
  Non alimentatele dal 5 V della scheda.
- **WS2813 a 3,3 V**: con VCC a 5 V, un segnale dati a 3,3 V è al limite. Provatelo subito. Se non va, fate un traslatore
  di livello con un transistor (presenti nell'inventario) o abbassate leggermente la VCC della strip.
- **Due percorsi di sicurezza**: visione su Linux → comandi al MCU. In più PIR + ToF letti **direttamente dal MCU**:
  se Linux muore, il MCU vede comunque il pedone e mette il giallo lampeggiante.
- **Monitoraggio della lampada**: misurate la corrente della strip in ciascuno stato (OFF, ambra, rosso) e fissate le
  soglie: ±30% rispetto al valore atteso → guasto.

## Bilancio energetico (da misurare col Coulomb Counter)

- LiPo 1000 mAh × 3,7 V = **3,7 Wh**.
- Esempio: se la UNO Q con camera e AI consuma **3 W** (ipotesi, da misurare), l'autonomia è circa **1 h**
  (3,7 / 3 × 80% di efficienza).
- Nel pitch: "batteria tampone: in blackout il sistema resta in giallo lampeggiante per X minuti", con X misurato.
  **Non** "autoalimentato a energia solare".

## Da verificare subito

- [ ] IMX219 funzionante sulla Media Carrier con la UNO Q (altrimenti → webcam USB).
- [ ] Tensione di I/O della UNO Q (3,3 V?) e posizione dell'interruttore del Base Shield.
- [ ] La WS2813 funziona con il segnale a 3,3 V?
- [ ] Il Grove MP3 V4 include l'altoparlante?
- [ ] Consumo reale della UNO Q a pieno carico.
