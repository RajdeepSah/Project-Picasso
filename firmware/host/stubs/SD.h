// Simulated SD card exposing the subset of the SD 1.2.4 API the sketch uses.
#ifndef PICASSO_HOST_SD_H
#define PICASSO_HOST_SD_H

#include "Arduino.h"

#define FILE_READ 0

class File {
 public:
  File() : open_(false), position_(0) {}
  int read();
  int available();
  bool seek(uint32_t position);
  uint32_t size();
  void close();
  operator bool() const { return open_; }

 private:
  friend class SDClass;
  bool open_;
  uint32_t position_;
};

class SDClass {
 public:
  bool begin(uint8_t chipSelect);
  void end();
  File open(const char* path, uint8_t mode = FILE_READ);
};

extern SDClass SD;

#endif
