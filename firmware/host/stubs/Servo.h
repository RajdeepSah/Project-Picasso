#ifndef PICASSO_HOST_SERVO_H
#define PICASSO_HOST_SERVO_H

#include "Arduino.h"

class Servo {
 public:
  uint8_t attach(int pin);
  void write(int angle);
};

#endif
