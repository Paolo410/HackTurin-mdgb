#pragma once
struct Adafruit_SGP30 { int eCO2 = 400, TVOC = 0; bool begin() { return true; } bool IAQmeasure() { return true; } };
