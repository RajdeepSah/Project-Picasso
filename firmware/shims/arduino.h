// TinyStepper_28BYJ_48 1.0.0 includes <arduino.h>, which only resolves on
// case-insensitive filesystems. Linux builds add this directory to the include
// path so the unmodified vendored library compiles. Do not use it on
// Windows/macOS, where <arduino.h> already finds the core header.
#ifndef PICASSO_ARDUINO_CASE_SHIM
#define PICASSO_ARDUINO_CASE_SHIM
#include <Arduino.h>
#endif
