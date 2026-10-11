// Runs the logic of the sketch on a PC with a fake clock: cycle, requests of the vision, fail-safe, RFID, quiet buzzer
// for the technician. Build and run: firmware/unoq_mcu/host_test/run.sh (a fake badge, never the real one).
#include "Arduino.h"
unsigned long fakeNow = 0;
std::map<int, int> pins;
std::vector<std::pair<int, int>> tones;
int fakeLight = 500;
float fakeAccelZ = 1.0f;
FakeSerial Serial1;
#include "Arduino_RouterBridge.h"
FakeBridge Bridge;
#include "Arduino_Modulino.h"
FakeModulino Modulino;
#include "sketch.ino"
#include <cassert>
#include <cstdio>

static char lamp() { return pins[LED_GREEN] ? 'G' : pins[LED_YELLOW] ? 'Y' : pins[LED_RED] ? 'R' : '-'; }
static bool visionOn = false, pedPresent = false, hold = false, redNow = false, techOn = false;
static int extendS = 0;
// Advances the fake clock in steps of 10 ms; the "vision" sends a heartbeat every 100 ms and a C1 every second.
static void run(unsigned long ms) {
  for (unsigned long end = fakeNow + ms; fakeNow < end; fakeNow += 10) {
    if (visionOn && fakeNow % 100 == 0) assert(Bridge.line_fn(String("{\"v\":1,\"hb\":7}")));
    if (visionOn && fakeNow % 1000 == 0) {
      String c1 = String("{\"v\":1,\"seq\":3,\"t_ms\":1739012345678,\"state\":\"") + (pedPresent ? "PRESENCE" : "IDLE") +
                  "\",\"led\":\"OFF\",\"green_s\":9,\"req\":{\"ped_green_extend_s\":" + String(extendS) + ",\"veh_red_hold\":" +
                  (hold ? "true" : "false") + ",\"veh_red_now\":" + (redNow ? "true" : "false") + ",\"flash\":false},\"lcd\":\"\",\"oled\":\"\",\"reason\":\"a \\\"state\\\":\\\"X\\\" in the text\",\"tech\":" + (techOn ? "true" : "false") + "}";
      assert(Bridge.line_fn(c1));
    }
    loop();
  }
}
// Seconds the lamp stays on one colour, starting from the moment it turns to it.
static double lasts(char colour) {
  while (lamp() != colour) run(10);
  unsigned long t0 = fakeNow;
  while (lamp() == colour) run(10);
  return (fakeNow - t0) / 1000.0;
}
static int count(const char *method, const char *contains) {
  int n = 0;
  for (auto &m : Bridge.sent) if (m.first == method && m.second.find(contains) != std::string::npos) n++;
  return n;
}

int main() {
  setup();
  assert(lamp() == 'G');
  printf("normal cycle: yellow %.1f s, red %.1f s, green %.1f s\n", lasts('Y'), lasts('R'), lasts('G'));

  assert(jsonValue(String("{\"v\":1,\"state\": \"WARN_DRIVER\",\"req\":{\"ped_green_extend_s\":7,\"veh_red_hold\":true}}"), "state") == "WARN_DRIVER");
  assert(!Bridge.line_fn(String("{\"v\":1,\"nothing\":0}")));

  visionOn = true; pedPresent = true;
  lasts('R');                                  // sync: start measuring from a fresh green
  double g = lasts('G');
  printf("an ordinary pedestrian seen by the vision: vehicle green still %.1f s\n", g);
  assert(g > 19.9 && g < 20.2);
  extendS = 7;                                 // somebody who needs more time (wheelchair, slow walker)
  double r = lasts('R');
  printf("pedestrian green extended by 7 s: red %.1f s\n", r);
  assert(r > 26.9 && r < 27.2);
  extendS = 99;
  r = lasts('R');
  printf("extension of 99 s asked: red %.1f s (limit 20 + 15)\n", r);
  assert(r > 34.9 && r < 35.2);
  extendS = 0; hold = true;
  r = lasts('R');
  printf("red hold never released: red %.1f s (limit 20 + 20)\n", r);
  assert(r > 39.9 && r < 40.2);

  // Red at once: a child on its own or a free animal, seen when the green has been on for 12 s.
  hold = false;
  while (lamp() != 'G') run(10);
  run(12000);
  redNow = true; hold = true;                  // the vision asks both, as rules.py does
  unsigned long asked = fakeNow;
  while (lamp() == 'G') run(10);
  unsigned long yellowAt = fakeNow;
  double y = lasts('Y') ;
  printf("red at once asked at 12 s of green: yellow after %lu ms, short yellow %.1f s, then red\n", yellowAt - asked, y);
  assert(yellowAt - asked <= 1100 && y > 1.4 && y < 1.6 && lamp() == 'R');
  r = lasts('R');
  printf("red held while the child is there: %.1f s (limit 20 + 20)\n", r);
  assert(r > 39.9 && r < 40.2);
  g = lasts('G');
  printf("still there after the limit: green for its minimum, %.1f s, then red again\n", g);
  assert(g > 7.9 && g < 8.2);
  redNow = false; hold = false;                // the child left: back to the normal cycle
  lasts('R'); g = lasts('G');
  assert(g > 19.9 && g < 20.2);
  hold = true;

  // Fail-safe: the vision dies during a held red.
  while (lamp() != 'R') run(10);
  run(3000);
  int before = count("mcu_event", "failsafe");
  visionOn = false;
  unsigned long t0 = fakeNow;
  while (count("mcu_event", "failsafe") == before) run(10);
  printf("vision stopped: fail-safe after %lu ms\n", fakeNow - t0);
  assert(fakeNow - t0 <= 620);
  r = lasts('G'); r = lasts('R');
  printf("after the fail-safe: red %.1f s (normal cycle, requests forgotten)\n", r);
  assert(r > 19.9 && r < 20.2);
  g = lasts('G');
  assert(g > 19.9 && g < 20.2);

  // RFID: three wrong badges lock the reader for a minute, the traffic light keeps cycling.
  for (int i = 0; i < 3; i++) { for (char c : std::string("111111111111")) Serial1.in.push_back(c); run(500); }
  assert(count("rfid_status", "BLOCCATO PER 60") == 1);
  char startLamp = lamp();
  unsigned long loops0 = fakeNow;
  for (char c : std::string(SECRET_TECH_BADGE)) Serial1.in.push_back(c);   // right badge during the lockout: ignored
  run(30000);
  assert(count("rfid_status", "CONSENTITO") == 0);
  bool changed = false;
  for (int i = 0; i < 4000 && !changed; i++) { run(10); changed = lamp() != startLamp; }
  assert(changed);
  run(31000);
  assert(count("rfid_status", "SBLOCCATO") == 1);
  size_t tonesAtBadge = tones.size();
  for (char c : std::string(SECRET_TECH_BADGE)) Serial1.in.push_back(c);
  run(500);
  assert(count("rfid_status", "CONSENTITO") == 1);
  assert(tones.size() == tonesAtBadge + 2);                              // the badge beep still sounds
  assert(count("mcu_event", "\"type\":\"tamper\",\"code\":3") == 1);   // the badge reaches the vision
  printf("RFID: lockout of 60 s without stopping the traffic light, then the right badge is accepted (%lu s simulated)\n", (fakeNow - loops0) / 1000);

  // TECHNICIAN AT THE NODE (C1 "tech"): no sound from the badge to the logout.
  // 1. Badge just accepted, no vision: quiet for 2 minutes, the shock is still reported.
  fakeAccelZ = 2.0f;
  size_t t1 = tones.size();
  int alarms1 = count("alarm_status", "FURTO");
  run(1000);
  fakeAccelZ = 1.0f;
  run(1500);
  printf("technician: shock right after the badge: beeps %zu, alarms %d\n", tones.size() - t1, count("alarm_status", "FURTO") - alarms1);
  assert(tones.size() == t1 && count("alarm_status", "FURTO") > alarms1);
  run(TECH_LOGIN_MS);                         // nobody logged in: after 2 minutes the buzzer is back
  t1 = tones.size();
  fakeAccelZ = 2.0f; run(1000); fakeAccelZ = 1.0f; run(1500);
  printf("technician: no login within 2 min, shock: beeps %zu\n", tones.size() - t1);
  assert(tones.size() >= t1 + 5);
  run(11000);
  // 2. Badge, then the vision says "tech" (logged in): quiet well beyond 2 minutes, until "tech" goes false.
  visionOn = true;
  run(2000);
  for (char c : std::string(SECRET_TECH_BADGE)) Serial1.in.push_back(c);
  run(500);
  techOn = true;
  run(TECH_LOGIN_MS + 60000);
  t1 = tones.size();
  fakeAccelZ = 2.0f; run(1000); fakeAccelZ = 1.0f; run(1500);
  printf("technician logged in for 3 min, shock: beeps %zu\n", tones.size() - t1);
  assert(tones.size() == t1);
  for (char c : std::string("111111111111")) Serial1.in.push_back(c);   // a wrong badge: no triple beep either
  run(500);
  assert(tones.size() == t1);
  techOn = false;                             // logout
  unsigned long out = fakeNow;
  run(1000);                                  // the next C1 carries tech:false
  run(11000);
  t1 = tones.size();
  fakeAccelZ = 2.0f; run(1000); fakeAccelZ = 1.0f; run(1500);
  printf("after the logout, shock: beeps %zu\n", tones.size() - t1);
  assert(tones.size() >= t1 + 5);
  // 3. Logout within the 2 minutes: the buzzer is back at once, not at the end of the 2 minutes.
  run(11000);
  for (char c : std::string(SECRET_TECH_BADGE)) Serial1.in.push_back(c);
  run(500);
  techOn = true; run(2000); techOn = false; run(1100);
  t1 = tones.size();
  fakeAccelZ = 2.0f; run(1000); fakeAccelZ = 1.0f; run(1500);
  printf("logout 3 s after the badge, shock: beeps %zu\n", tones.size() - t1);
  assert(tones.size() >= t1 + 5);
  // 4. Logged in and the vision dies: fail-safe, the buzzer is back (the anti-theft does not stay quiet).
  run(11000);
  for (char c : std::string(SECRET_TECH_BADGE)) Serial1.in.push_back(c);
  run(500);
  techOn = true;
  run(TECH_LOGIN_MS + 1000);
  visionOn = false;
  run(1000);
  t1 = tones.size();
  fakeAccelZ = 2.0f; run(1000); fakeAccelZ = 1.0f; run(1500);
  printf("logged in, vision stopped: beeps %zu\n", tones.size() - t1);
  assert(tones.size() >= t1 + 5);
  techOn = false;
  (void)out;
  run(11000);

  // Shock: alarm notified, beeps without blocking.
  int alarms0 = count("alarm_status", "FURTO"), lines0 = count("mcu_event", "\"code\":1");
  fakeAccelZ = 2.0f;
  size_t tonesBefore = tones.size();
  run(1000);            // one reading of the sensors with the shock
  fakeAccelZ = 1.0f;
  run(1500);            // the five beeps play while the loop keeps running
  printf("shock: alarms %d, beeps %zu\n", count("alarm_status", "FURTO") - alarms0, tones.size() - tonesBefore);
  assert(count("alarm_status", "FURTO") >= alarms0 + 1 && tones.size() >= tonesBefore + 5);
  fakeAccelZ = 2.0f;
  run(5000);            // it keeps shaking: an alarm at every reading, but one line for the vision every 10 s
  fakeAccelZ = 1.0f;
  int alarms = count("alarm_status", "FURTO") - alarms0, lines = count("mcu_event", "\"code\":1") - lines0;
  printf("shaking for 6 s: alarms %d, lines for the vision %d\n", alarms, lines);
  assert(alarms >= 5 && lines == 1);
  printf("all checks passed\n");
  return 0;
}
