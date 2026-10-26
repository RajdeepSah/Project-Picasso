// Minimal Arduino API for host builds. Time, pins, keypad ADC, servo, SD card
// and display are simulated in sim.cpp; nothing here touches hardware.
#ifndef PICASSO_HOST_ARDUINO_H
#define PICASSO_HOST_ARDUINO_H

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef uint8_t byte;
typedef bool boolean;

#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define A0 14
#define A1 15
#define A2 16
#define PI 3.1415926535897932384626433832795

#define PROGMEM
#define PGM_P const char*
#define PSTR(text) (text)
#define strncpy_P strncpy
#define strncat_P strncat

class __FlashStringHelper;
#define F(text) (reinterpret_cast<const __FlashStringHelper*>(text))

unsigned long millis();
unsigned long micros();
void delay(unsigned long ms);
void delayMicroseconds(unsigned int us);
void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t value);
int analogRead(uint8_t pin);

class HardwareSerial {
 public:
  void begin(unsigned long baud);
  void print(const char* text);
  void print(const __FlashStringHelper* text);
  void print(unsigned long value);
  void print(unsigned int value);
  void print(int value);
  void println(const char* text);
  void println(const __FlashStringHelper* text);
  void println();
};

extern HardwareSerial Serial;

#endif
