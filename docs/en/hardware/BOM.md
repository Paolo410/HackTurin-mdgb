# BOM — Smart Crossing (GOMA challenge)

> English translation of [`hardware/BOM.md`](../../../hardware/BOM.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

Owner: electronics engineer. Based on the file `docs/Materiale di elettronica da reperire.xlsx`
(columns: **Kit** = already in the team kit · **Inv** = shared inventory, to request).
It serves three purposes:
1. request the components and know what is missing;
2. have the costs for the pitch (a device of about 150–250 € against the about 16,700 € per crossing spent in Como);
3. be the reference for wiring and pinout (the Pinout section is in `docs/CONTRACTS.md`).

Priority: **P1** = essential for the demo · **P2** = very useful · **P3** = only if time is left.

## To request (all available in the list)

| Component | Source | Qty | Use | Priority |
|---|---|---|---|---|
| Arduino UNO Q 4 GB | Kit | 1 | Brain: vision on Linux, safety on the MCU | P1 |
| Arduino UNO Media Carrier | Inv | 1 | CSI ports for the cameras. **Check IMX219 support at once** | P1 |
| Sony IMX219 8MP camera | Inv | 2 | 1 on the crossing + 1 spare (or on the approach lane at lower FPS) | P1 |
| Grove Base Shield V2 | Inv | 1 | **Switch on 3.3 V** (UNO Q logic at 3.3 V: to check) | P1 |
| Grove 4-pin cables 20 cm / jumper→Grove / 5 cm | Inv | 6 / 4 / 2 | Wiring of the Grove modules | P1 |
| Breadboard / perfboard | Inv | 2 / 1 | Prototype, then a soldered assembly for the demo | P1 |
| Jumpers M-M, F-F, M-F | Kit | 10+10+10 | — | P1 |
| **Grove WS2813 RGB LED Strip 1 m (30 LEDs)** | Inv | 2 | **Visible signalling**: 1 = amber/red towards vehicles, 1 = red on the ground for pedestrians. External 5 V supply (see notes) | P1 |
| **Grove RGB LED Ring (16 WS2813)** | Inv | 1 | Pedestrian "lantern" on the pole + fail-safe yellow | P1 |
| Grove Passive Buzzer | Inv | 1 | Sound warning in WARN_PEDESTRIAN | P1 |
| Grove Light Sensor | Inv | 1 | Night mode + adaptive brightness of the LEDs | P1 |
| Grove AHT20 (temperature/humidity) | Inv | 1 | Flows ↔ weather correlation in the aggregates + risk of fogged lens | P2 |
| Resistors + capacitors | Inv | a few | 330 Ω in series on the data line of the strip, ~1000 µF electrolytic capacitor on the strip supply | P1 |
| USB-C module (breakout) | Inv | 2 | Separate 5 V supply for the LED strips | P1 |
| Grove 16x2 LCD | Inv | 1 | Display towards drivers: "PEDONE 47 km/h" / "ANIMALI IN STRADA" (instead of the LED matrix, which is not available) | P2 |
| Grove OLED 0.96" | Inv | 1 | Display towards pedestrians: countdown, "ATTENDI: auto a 45 km/h" | P2 |
| **Grove Digital PIR** | Inv | 1 | Presence in the waiting area **independent from the vision** (works in the dark), read by the MCU → test with the camera unplugged | P2 |
| **Modulino Distance** (ToF, about 1.3 m) | Kit | 1 | Close presence at the pole / "touchless" button. Also on the MCU: second safety path | P2 |
| **Grove Thermal Imaging Camera (MLX90621, 16x4, 60°)** | Inv | 1 | Heat strip along the kerb: night presence per zone (at 4 m each column covers about 29 cm). It does **not** classify | P2 |
| **Grove 2.5A DC Current Sensor (ACS70331)** | Inv | 1 | **Lamp monitoring**: checks that the LEDs really light up (expected vs measured current). On a fault → DEGRADED + maintenance alarm. "Safety" argument for GOMA | P2 |
| Modulino Movement (IMU) | Kit | 1 | Pole hit or camera moved → calibration no longer valid → DEGRADED + event | P2 |
| Grove Touch Sensor | Inv | 1 | **Accessible** pedestrian call button (no force needed) | P2 |
| Grove Magnetic Switch | Inv | 1 | Case opening sensor (tampering) | P2 |
| Grove Coulomb Counter | Inv | 1 | Measures the real consumption → numbers for the energy slide | P2 |
| Grove MP3 Module V4 | Inv | 1 | Voice messages for visually impaired people ("Please wait, vehicle approaching"). Check whether the speaker is included | P3 |
| Potentiometer | Kit | 1 | Demo knob: simulates the vehicle speed on the model (or sets W live) | P3 |
| LiPo 1000 mAh + Waveshare Solar Charger + Mini Solar Panel | Inv | 1+1+1 | Only as a **backup battery** (see energy budget) | P3 |
| Grove Sound Sensor | Inv | 1 | Confirmation of incidents (sound peak + trajectory rule) | P3 |
| Cardboard, sticks, rubber bands, magnets + 3D printers | Inv | as needed | **Model** of the crossing + case + camera mount | P1 |

## From the previous BOM: what changes

| Before | Now | Reason |
|---|---|---|
| 3 mm/5 mm LEDs as signalling | WS2813 strip + LED Ring | Available and visible |
| 8x32 LED matrix | Grove LCD 16x2 | The matrix is not in the list |
| HLK-LD2450 radar | PIR + Modulino Distance | The radar is not in the list. Two **non-visual** sensors on the MCU remain for the fail-safe |
| MLX90640 (32x24) | MLX90621 (16x4) | Only the 16x4 is in the list: presence per zone, no classification |
| Micro switch ×2 | Touch (call) + Magnetic switch (case) | Better suited to the purpose |
| NFC PN532 | Removed | Brings no points (the AHT20 stays, for the weather correlation) |
| XIAO ESP32 for V2X | Removed | The "car dashboard" is a **smartphone** receiving from the UNO Q over Wi-Fi/BLE |
| (new) | ACS70331 for lamp monitoring | Closes the safety loop: command → LED verified on |

Not to request: SGP30/SGP41, 125 kHz RFID, servo, relay, electromagnet, Hall/tilt/vibration/piezo sensors (the Modulino
Movement covers them), FSR, encoder, joystick, IR receiver.

## Not in the list: to bring from home or to ask for

| What | Why | Priority |
|---|---|---|
| **USB webcam** (+ USB-C hub if needed) | Plan B if the IMX219 does not work on the Media Carrier. Without it, **no vision** | P1 |
| 2 USB-C 5 V/3 A chargers + power bank | Supply of the UNO Q and of the LED strips | P1 |
| Tripod or pole (2–3 m) | View from above for the road tests; for the model a printed mount is enough | P1 |
| Smartphone | "Car dashboard" for the V2X demo and dashboard | P2 |

## Technical notes

- **WS2813 and power**: 30 LEDs at full white draw up to about 1.8 A. Limit the brightness in software (about 30% →
  about 0.5 A) and power the strips from a separate 5 V supply, with ground in common with the UNO Q. Do not power them
  from the 5 V of the board.
- **WS2813 at 3.3 V**: with VCC at 5 V, a 3.3 V data signal is at the limit. Test it at once. If it does not work, build
  a level shifter with a transistor (in the inventory) or lower the VCC of the strip slightly.
- **Two safety paths**: vision on Linux → commands to the MCU. In addition PIR + ToF read **directly by the MCU**: if
  Linux dies, the MCU still sees the pedestrian and turns on the flashing yellow.
- **Lamp monitoring**: measure the current of the strip in each state (OFF, amber, red) and set the thresholds: ±30%
  from the expected value → fault.

## Energy budget (to measure with the Coulomb Counter)

- LiPo 1000 mAh × 3.7 V = **3.7 Wh**.
- Example: if the UNO Q with camera and AI uses **3 W** (assumption, to measure), the autonomy is about **1 h**
  (3.7 / 3 × 80% efficiency).
- In the pitch: "backup battery: in a blackout the system stays in flashing yellow for X minutes", with X measured.
  **Not** "self-powered by solar energy".

## To verify at once

- [ ] IMX219 working on the Media Carrier with the UNO Q (otherwise → USB webcam).
- [ ] I/O voltage of the UNO Q (3.3 V?) and position of the Base Shield switch.
- [ ] Does the WS2813 work with the 3.3 V signal?
- [ ] Does the Grove MP3 V4 include the speaker?
- [ ] Real consumption of the UNO Q at full load.
