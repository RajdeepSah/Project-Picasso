// In-memory EEPROM for host builds. Erased cells read 0xFF, as on the AVR.
#ifndef PICASSO_HOST_EEPROM_H
#define PICASSO_HOST_EEPROM_H

#include "Arduino.h"

namespace sim {
extern uint8_t eeprom[1024];
}

class EEPROMClass {
 public:
  template <typename T>
  T& get(int address, T& value) {
    memcpy(&value, sim::eeprom + address, sizeof(T));
    return value;
  }
  template <typename T>
  const T& put(int address, const T& value) {
    memcpy(sim::eeprom + address, &value, sizeof(T));
    return value;
  }
};

extern EEPROMClass EEPROM;

#endif
