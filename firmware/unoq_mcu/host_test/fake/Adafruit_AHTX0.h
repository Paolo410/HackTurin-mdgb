#pragma once
struct sensors_event_t { float temperature = 21.5f; float relative_humidity = 40.0f; };
struct Adafruit_AHTX0 { bool begin() { return true; } bool getEvent(sensors_event_t *, sensors_event_t *) { return true; } };
