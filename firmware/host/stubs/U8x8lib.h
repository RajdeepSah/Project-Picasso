#ifndef PICASSO_HOST_U8X8_H
#define PICASSO_HOST_U8X8_H

#include "Arduino.h"

#define U8X8_PIN_NONE 255
extern const uint8_t u8x8_font_amstrad_cpc_extended_r[];

// Records text rows. Calls advance simulated time to model blocking I2C writes.
class U8X8_SSD1306_128X64_NONAME_HW_I2C {
 public:
  explicit U8X8_SSD1306_128X64_NONAME_HW_I2C(uint8_t reset = U8X8_PIN_NONE) { (void)reset; }
  void begin();
  void setFont(const uint8_t* font);
  void clear();
  void drawString(uint8_t column, uint8_t row, const char* text);
  void draw1x2String(uint8_t column, uint8_t row, const char* text);
};

#endif
