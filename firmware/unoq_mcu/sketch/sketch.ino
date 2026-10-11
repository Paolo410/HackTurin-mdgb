#include <Arduino.h>
#include <Arduino_Modulino.h>
#include <Arduino_RouterBridge.h>
#include <Adafruit_AHTX0.h>
#include <Adafruit_SGP30.h>
#include <math.h>

// MDGB (Paolo, da rivedere con Salvatore): lo sketch di Salvatore (app "test", versione del 10/10 sera, con
// buzzer su A5 e luce su A0) con in più il semaforo comandato dalla visione (docs/CONTRACTS.md v1: C1, C2, C5).
// Cosa cambia rispetto all'originale: LEGGIMI.md della proposta (mdgb-app-proposta.zip).

// =========================================================================
// Codice del badge del tecnico autorizzato: in arduino_secrets.h, che NON va nel repo (.gitignore).
// Si crea copiando arduino_secrets.h.example e scrivendo il codice del badge.
#include "arduino_secrets.h"
String AUTHORIZED_TAG = SECRET_TECH_BADGE;
// =========================================================================

ModulinoMovement movement;
Adafruit_AHTX0 aht;
Adafruit_SGP30 sgp;

#define rfidSerial Serial1

// PIN HARDWARE
const int BUZZER_PIN = A5;       // Buzzer passivo spostato su A5
const int LIGHT_SENSOR_PIN = A0; // Sensore Luce sulla porta A1 dello Shield Grove
const int LED_GREEN = 13;        // LED Verde
const int LED_YELLOW = 12;       // LED Giallo
const int LED_RED = 11;          // LED Rosso

// CONTATORE E SICUREZZA RFID
int failedAttempts = 0;
bool lockedOut = false;              // blocco RFID in corso (non ferma piu' il resto dello sketch)
unsigned long lockoutStartMs = 0;
unsigned long lockoutDurationMs = 0;
unsigned long lockoutBeepMs = 0;

// SOGLIE ACCELERAZIONE ANOMALA (1.0g è la gravità a riposo)
const float ACCEL_UPPER_THRESHOLD = 1.15; // Sopra 1.35g -> Scossa / Movimento
const float ACCEL_LOWER_THRESHOLD = 0.65; // Sotto 0.65g -> Caduta / Spostamento brusco

// Timers
unsigned long previousSensorMillis = 0;
const long sensorInterval = 500;

// =========================================================================
// SEMAFORO (centralina simulata). I tre LED sono la lanterna dei veicoli:
// rosso per i veicoli = verde per i pedoni.
// I limiti sono costanti del firmware: Linux puo' solo chiedere, entro questi limiti.
// =========================================================================
const unsigned long VEH_GREEN_MS = 20000UL;      // verde veicoli del ciclo normale
const unsigned long VEH_GREEN_MIN_MS = 8000UL;   // verde veicoli minimo: nemmeno il rosso d'urgenza lo accorcia
const unsigned long VEH_YELLOW_MS = 3000UL;      // giallo
const unsigned long VEH_YELLOW_URGENT_MS = 1500UL; // giallo breve prima del rosso d'urgenza (bambino solo, animale)
const unsigned long VEH_RED_MS = 20000UL;        // rosso veicoli (verde pedonale) del ciclo normale: il tempo per attraversare
const unsigned long PED_EXTEND_MAX_MS = 15000UL; // estensione massima del verde pedonale
const unsigned long RED_HOLD_MAX_MS = 20000UL;   // rosso veicoli trattenuto al massimo cosi' a lungo oltre il normale
const unsigned long HB_TIMEOUT_MS = 500UL;       // senza heartbeat piu' a lungo: fail-safe (ciclo normale)
const unsigned long TECH_LOGIN_MS = 120000UL;    // dopo il badge: 2 minuti di cicalino muto per il login (anche senza visione)

enum Phase { VEH_GREEN, VEH_YELLOW, VEH_RED };
Phase phase = VEH_GREEN;
unsigned long phaseStartMs = 0;

// Richieste della visione (C1). Valgono solo finche' arrivano gli heartbeat (C2).
bool hbEverSeen = false;
unsigned long lastHbMs = 0;
bool visionAlive = false;
unsigned long reqExtendMs = 0;    // req.ped_green_extend_s: verde pedonale in piu' per chi ne ha bisogno, gia' limitato
bool reqRedHold = false;          // req.veh_red_hold: chi ha bisogno di tempo e' ancora sulle strisce
bool reqRedNow = false;           // req.veh_red_now: bambino non accompagnato o animale libero -> rosso subito
bool urgentYellow = false;        // il giallo in corso e' quello breve

// TECNICO AL NODO: dal badge al logout il cicalino non suona (C1 "tech", ai/DECISIONS.md punto 36).
bool techBadge = false;           // badge accettato: muto per TECH_LOGIN_MS, il tempo per il login
unsigned long techBadgeMs = 0;
bool reqTech = false;             // C1 "tech": il tecnico e' ancora collegato alla pagina (vale solo con gli heartbeat)

bool buzzerMuted(unsigned long now) {
  return (techBadge && now - techBadgeMs < TECH_LOGIN_MS) || (visionAlive && reqTech);
}

// =========================================================================
// BUZZER senza delay(): mentre suona, semaforo e Bridge continuano a girare.
// =========================================================================
int beepFreq = 0;
int beepOnMs = 0;
int beepOffMs = 0;
int beepsLeft = 0;
unsigned long beepNextMs = 0;
bool beepForce = false;           // la serie in corso suona anche con il tecnico al nodo (conferma del badge)

// CICALINO: 1 = acceso (riacceso da Salvatore l'11/10), 0 = spento. Tutti i suoni passano da qui: badge, errore,
// blocco, antifurto. Con il tecnico al nodo (buzzerMuted) restano muti. Messaggi e semaforo non cambiano.
#ifndef BUZZER_ENABLED
#define BUZZER_ENABLED 1
#endif

void playBeep(int frequency, int durationMs) {
  if (BUZZER_ENABLED && !buzzerMuted(millis())) {
    tone(BUZZER_PIN, frequency, durationMs);
  }
}

// Solo per la conferma del badge: suona anche con il tecnico al nodo.
void playBeepAlways(int frequency, int durationMs) {
  if (BUZZER_ENABLED) {
    tone(BUZZER_PIN, frequency, durationMs);
  }
}

// Una serie di bip uguali: parte subito e prosegue da updateBeeps().
void startBeeps(int frequency, int onMs, int offMs, int count) {
  beepFreq = frequency;
  beepOnMs = onMs;
  beepOffMs = offMs;
  beepsLeft = count;
  beepNextMs = millis();
  beepForce = false;
}

void updateBeeps(unsigned long now) {
  if (beepsLeft > 0 && (long)(now - beepNextMs) >= 0) {
    if (beepForce) {
      playBeepAlways(beepFreq, beepOnMs);
    } else {
      playBeep(beepFreq, beepOnMs);
    }
    beepNextMs = now + beepOnMs + beepOffMs;
    beepsLeft--;
  }
}

// TRIPLO BIP per errore RFID
void playTripleBeep() {
  startBeeps(400, 100, 100, 3);
}

// Allarme Furto: 5 BIP veloci a 2700Hz. I LED non lampeggiano piu': sono il semaforo.
unsigned long lastTheftEventMs = 0;
bool theftEventSent = false;

void triggerTheftAlarm() {
  Bridge.notify("alarm_status", "ALLARME: TENTATO FURTO! Accelerazione anomala rilevata!");
  startBeeps(2700, 80, 60, 5); // Frequenza di risonanza 2700Hz

  // Lo stesso allarme verso la visione, come riga C5 del contratto (tamper, code 1 = urto), al massimo una
  // ogni 10 s: la visione la mostra al tecnico e, quando ci sara' la rete, arrivera' alla centrale.
  unsigned long now = millis();
  if (!theftEventSent || now - lastTheftEventMs >= 10000UL) {
    theftEventSent = true;
    lastTheftEventMs = now;
    Bridge.notify("mcu_event", "{\"v\":1,\"src\":\"mcu\",\"type\":\"tamper\",\"code\":1}");
  }
}

// BLOCCO RFID: per la sua durata il badge viene ignorato, il semaforo continua.
void triggerLockout(unsigned long durationMs) {
  String lockMsg = "SISTEMA BLOCCATO PER " + String(durationMs / 1000) + " SECONDI!";
  Bridge.notify("rfid_status", lockMsg.c_str());
  lockedOut = true;
  lockoutStartMs = millis();
  lockoutDurationMs = durationMs;
  lockoutBeepMs = lockoutStartMs;
  playBeep(400, 200);
}

void updateLockout(unsigned long now) {
  if (!lockedOut) {
    return;
  }
  if (now - lockoutStartMs >= lockoutDurationMs) {
    lockedOut = false;
    Bridge.notify("rfid_status", "SBLOCCATO - Puoi riprovare l'RFID");
  } else if (now - lockoutBeepMs >= 1000) {
    lockoutBeepMs = now;
    playBeep(400, 200);
  }
}

// =========================================================================
// SEMAFORO
// =========================================================================
void setPhase(Phase next, unsigned long now) {
  phase = next;
  phaseStartMs = now;
  digitalWrite(LED_GREEN, next == VEH_GREEN ? HIGH : LOW);
  digitalWrite(LED_YELLOW, next == VEH_YELLOW ? HIGH : LOW);
  digitalWrite(LED_RED, next == VEH_RED ? HIGH : LOW);
  if (next == VEH_GREEN) {
    Bridge.notify("led_status", "LED VERDE acceso (Pin 13)");
  } else if (next == VEH_YELLOW) {
    Bridge.notify("led_status", "LED GIALLO acceso (Pin 12)");
  } else {
    Bridge.notify("led_status", "LED ROSSO acceso (Pin 11)");
  }
}

void updateSignal(unsigned long now) {
  unsigned long elapsed = now - phaseStartMs;

  if (phase == VEH_GREEN) {
    // Rosso d'urgenza (bambino non accompagnato, animale libero): giallo breve e poi rosso, appena il verde
    // ha fatto il suo minimo. Un pedone qualunque non cambia il ciclo.
    bool urgent = visionAlive && reqRedNow && elapsed >= VEH_GREEN_MIN_MS;
    if (urgent || elapsed >= VEH_GREEN_MS) {
      urgentYellow = urgent;
      setPhase(VEH_YELLOW, now);
    }
  } else if (phase == VEH_YELLOW) {
    if (elapsed >= (urgentYellow ? VEH_YELLOW_URGENT_MS : VEH_YELLOW_MS)) {
      setPhase(VEH_RED, now);
    }
  } else {
    unsigned long redMs = VEH_RED_MS;
    if (visionAlive) {
      redMs += reqExtendMs;                      // verde pedonale esteso (gia' limitato a 15 s)
      if (reqRedHold || reqRedNow) {
        redMs = VEH_RED_MS + RED_HOLD_MAX_MS;    // rosso trattenuto finche' richiesto, fino al limite
      }
    }
    if (elapsed >= redMs) {
      setPhase(VEH_GREEN, now);
    }
  }
}

// =========================================================================
// VISIONE -> SEMAFORO (Bridge). Una riga JSON C1 o C2, senza '\n'.
// =========================================================================

// Valore di un campo in una riga JSON: il testo dopo "chiave": fino a ',' o '}' (senza virgolette).
String jsonValue(const String &line, const char *key) {
  String pattern = String("\"") + key + "\":";
  int start = line.indexOf(pattern);
  if (start < 0) {
    return "";
  }
  start += pattern.length();
  while (line.charAt(start) == ' ') {
    start++;
  }
  int end;
  if (line.charAt(start) == '"') {
    start++;
    end = line.indexOf('"', start);
    if (end < 0) {
      return "";
    }
  } else {
    end = start;
    while (end < (int)line.length() && line.charAt(end) != ',' && line.charAt(end) != '}') {
      end++;
    }
  }
  return line.substring(start, end);
}

// Registrata con provide_safe: gira nel thread di loop(), niente race con LED e semaforo.
// Qui dentro niente Bridge.call (rischio di deadlock, lo dice la libreria). true = riga valida.
bool mdgb_line(String line) {
  if (line.indexOf("\"hb\":") >= 0) {           // C2: heartbeat
    hbEverSeen = true;
    lastHbMs = millis();
    return true;
  }
  String state = jsonValue(line, "state");      // C1: comando
  if (state.length() == 0) {
    return false;
  }
  long extendS = jsonValue(line, "ped_green_extend_s").toInt();
  if (extendS < 0) {
    extendS = 0;
  }
  reqExtendMs = (unsigned long)extendS * 1000UL;
  if (reqExtendMs > PED_EXTEND_MAX_MS) {
    reqExtendMs = PED_EXTEND_MAX_MS;
  }
  reqRedHold = (jsonValue(line, "veh_red_hold") == "true");
  reqRedNow = (jsonValue(line, "veh_red_now") == "true");
  bool tech = (jsonValue(line, "tech") == "true");
  if (reqTech && !tech) {
    techBadge = false;            // logout (o login non fatto in tempo): il cicalino torna subito attivo
  }
  reqTech = tech;
  return true;
}

// FAIL-SAFE: senza heartbeat per piu' di 500 ms le richieste si annullano e il ciclo torna normale.
void updateVisionLink(unsigned long now) {
  // Confronto con segno: se un heartbeat arriva dopo la lettura di 'now', la differenza e' negativa, non enorme.
  bool alive = hbEverSeen && ((long)(now - lastHbMs) <= (long)HB_TIMEOUT_MS);
  if (alive && !visionAlive) {
    visionAlive = true;
    Bridge.notify("led_status", "VISIONE collegata: semaforo adattivo");
  } else if (!alive && visionAlive) {
    visionAlive = false;
    reqExtendMs = 0;
    reqRedHold = false;
    reqRedNow = false;
    reqTech = false;              // senza visione vale solo il silenzio dei 2 minuti dal badge
    Bridge.notify("led_status", "FAIL-SAFE: visione assente, ciclo normale");
    Bridge.notify("mcu_event", "{\"v\":1,\"src\":\"mcu\",\"type\":\"failsafe\",\"reason\":\"hb_timeout\"}");
  }
}

void setup() {
  Bridge.begin();
  Bridge.provide_safe("mdgb_line", mdgb_line);

  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LIGHT_SENSOR_PIN, INPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
  pinMode(LED_RED, OUTPUT);

  Modulino.begin();
  movement.begin();
  aht.begin();
  sgp.begin();
  rfidSerial.begin(9600);

  setPhase(VEH_GREEN, millis());   // al boot: ciclo normale finche' non arriva il primo heartbeat
}

void loop() {
  unsigned long now = millis();

  // 1. Semaforo, collegamento con la visione, buzzer, blocco RFID: niente delay()
  updateVisionLink(now);
  updateSignal(now);
  updateBeeps(now);
  updateLockout(now);

  // 2. Controllo RFID in tempo reale
  if (rfidSerial.available() > 0) {
    String rfidTag = "";
    while (rfidSerial.available()) {
      char c = rfidSerial.read();
      // Mantiene solo numeri e lettere, scartando i caratteri di controllo invisibili
      if (isAlphaNumeric(c)) {
        rfidTag += c;
      }
      delay(5);
    }

    if (lockedOut) {
      rfidTag = "";   // durante il blocco il badge viene letto e scartato
    }

    if (rfidTag.length() > 0) {
      Bridge.notify("rfid_data", rfidTag.c_str());

      // Confronto pulito tra le due stringhe Arduino
      if (rfidTag == AUTHORIZED_TAG) {
        failedAttempts = 0; // Azzera errori
        Bridge.notify("rfid_status", "ACCESSO CONSENTITO (Granted)");
        // Badge del tecnico verso la visione (riga C5: tamper, code 3): apre la pagina del tecnico.
        Bridge.notify("mcu_event", "{\"v\":1,\"src\":\"mcu\",\"type\":\"tamper\",\"code\":3}");
        techBadge = true;           // tecnico al nodo: cicalino muto fino al logout (o 2 minuti senza login)
        techBadgeMs = millis();
        startBeeps(2500, 120, 30, 2);
        beepForce = true;           // la conferma del badge si sente
      } else {
        failedAttempts++;

        if (failedAttempts < 3) {
          String errStr = "ACCESSO NEGATO (Errore " + String(failedAttempts) + "/3)";
          Bridge.notify("rfid_status", errStr.c_str());

          // TRIPLO BIP DI ERRORE
          playTripleBeep();
        } else {
          unsigned long lockoutTimeMs = 60000UL; // 1 Minuto (3° errore)

          if (failedAttempts == 4) {
            lockoutTimeMs = 300000UL; // 5 Minuti (4° errore)
          } else if (failedAttempts >= 5) {
            lockoutTimeMs = 900000UL; // 15 Minuti (5°+ errore)
          }

          triggerLockout(lockoutTimeMs);
        }
      }
    }
  }

  // 3. Lettura sensori e rilevamento antifurto
  if (now - previousSensorMillis >= sensorInterval) {
    previousSensorMillis = now;

    // Controllo Accelerometro IMU Modulino
    if (movement.update() == 1) {
      float x = movement.getX();
      float y = movement.getY();
      float z = movement.getZ();

      Bridge.notify("sensor_movement", x, y, z);

      // Calcolo del modulo del vettore accelerazione totale
      float totalAccel = sqrt(x * x + y * y + z * z);

      // SE RILEVA UN 'URTO' O SPOSTAMENTO ANOMALO -> SCATTA L'ALLARME
      if (totalAccel > ACCEL_UPPER_THRESHOLD || totalAccel < ACCEL_LOWER_THRESHOLD) {
        triggerTheftAlarm();
      }
    }

    // AHT20
    sensors_event_t humidity, temp;
    if (aht.getEvent(&humidity, &temp)) {
      Bridge.notify("sensor_env", temp.temperature, humidity.relative_humidity);
    }

    // SGP30
    if (sgp.IAQmeasure()) {
      Bridge.notify("sensor_air", (float)sgp.eCO2, (float)sgp.TVOC);
    }

    // Sensore Luce su A1
    int lightValue = analogRead(LIGHT_SENSOR_PIN);
    Bridge.notify("sensor_light", (float)lightValue);

    // Bip di avviso se coperto
    if (lightValue < 100) {
      //playBeep(1000, 150);
    }
  }
}
