// Minimal stand-in for the Arduino core, only to run the logic of the sketch on a PC.
#pragma once
#include <cmath>
#include <cstdlib>
#include <deque>
#include <map>
#include <string>
#include <vector>
#define HIGH 1
#define LOW 0
#define OUTPUT 1
const int A0 = 100, A1 = 101, A5 = 105;
#define INPUT 0
extern unsigned long fakeNow;
extern std::map<int, int> pins;
extern std::vector<std::pair<int, int>> tones;
extern int fakeLight;
inline unsigned long millis() { return fakeNow; }
inline void delay(unsigned long ms) { fakeNow += ms; }
inline void pinMode(int, int) {}
inline void digitalWrite(int pin, int v) { pins[pin] = v; }
inline int analogRead(int) { return fakeLight; }
inline void tone(int, int f, int d) { tones.push_back({f, d}); }
inline bool isAlphaNumeric(char c) { return isalnum((unsigned char)c); }
class String {
 public:
  std::string s;
  String() {}
  String(const char *c) : s(c) {}
  String(const std::string &c) : s(c) {}
  String(int v) : s(std::to_string(v)) {}
  String(long v) : s(std::to_string(v)) {}
  String(unsigned long v) : s(std::to_string(v)) {}
  unsigned int length() const { return s.size(); }
  const char *c_str() const { return s.c_str(); }
  char charAt(unsigned int i) const { return i < s.size() ? s[i] : 0; }
  int indexOf(const String &o, unsigned int from = 0) const { auto p = s.find(o.s, from); return p == std::string::npos ? -1 : (int)p; }
  int indexOf(const char *o) const { return indexOf(String(o)); }
  int indexOf(char c, unsigned int from = 0) const { auto p = s.find(c, from); return p == std::string::npos ? -1 : (int)p; }
  String substring(unsigned int a, unsigned int b) const { return String(s.substr(a, b - a)); }
  long toInt() const { return atol(s.c_str()); }
  String &operator+=(char c) { s += c; return *this; }
  bool operator==(const String &o) const { return s == o.s; }
  bool operator==(const char *o) const { return s == o; }
};
inline String operator+(const String &a, const String &b) { return String(a.s + b.s); }
inline String operator+(const String &a, const char *b) { return String(a.s + b); }
inline String operator+(const char *a, const String &b) { return String(std::string(a) + b.s); }
struct FakeSerial {
  std::deque<char> in;
  void begin(long) {}
  int available() { return in.size(); }
  char read() { char c = in.front(); in.pop_front(); return c; }
};
extern FakeSerial Serial1;
