#pragma once
#include "Arduino.h"
struct FakeBridge {
  std::vector<std::pair<std::string, std::string>> sent;   // (method, first argument as text)
  bool (*line_fn)(String) = nullptr;
  void begin() {}
  void provide_safe(const char *, bool (*fn)(String)) { line_fn = fn; }
  void notify(const char *m, const char *a) { sent.push_back({m, a}); }
  template <typename... T> void notify(const char *m, T...) { sent.push_back({m, ""}); }
};
extern FakeBridge Bridge;
