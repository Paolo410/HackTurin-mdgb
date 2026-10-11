#pragma once
struct FakeModulino { void begin() {} };
extern FakeModulino Modulino;
extern float fakeAccelZ;
struct ModulinoMovement { void begin() {} int update() { return 1; } float getX() { return 0; } float getY() { return 0; } float getZ() { return fakeAccelZ; } };
