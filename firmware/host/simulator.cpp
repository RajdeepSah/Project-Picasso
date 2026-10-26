// Host simulation of the canonical firmware. It compiles the real sketch and
// links the unmodified vendored TinyStepper library against modelled time,
// pins, keypad ADC, servo, SD card and display. Results are simulation
// evidence of the firmware logic only, never of the physical machine.
//
// A scenario script on stdin drives it, one command per line:
//   card <path> | nocard | nofile | fail_after <bytes>
//   boot | key <down|enter|esc> | wait <ms> | until <state> <timeout_ms> | report
#include "Arduino.h"
#include "SD.h"
#include "Servo.h"
#include "U8x8lib.h"
#include PICASSO_MACHINE_CONFIG

#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace sim {

// Modelled costs. Loop and ADC figures approximate a 16 MHz AVR; display
// figures assume the 400 kHz I2C clock U8g2 selects for this SSD1306
// (1024 bytes per clear, 16 bytes per double-height character). They shape
// timing, not correctness.
const uint64_t kLoopCostUs = 50;
const uint64_t kAnalogReadUs = 110;
const uint64_t kDisplayClearUs = 23000;
const uint64_t kDisplayCharUs = 400;

uint64_t now = 0;
int keypad = 1023;
uint8_t pins[32];

struct Motor {
  uint8_t pins[4];
  uint8_t pattern;
  long steps;
  uint64_t lastStep;
};
Motor motors[2] = {{{7, 8, 9, 10}, 0, 0, 0}, {{2, 3, 5, 6}, 0, 0, 0}};

std::vector<std::pair<uint64_t, int>> servoWrites;
bool gapPending = false;
int gapAngle = 0;
uint64_t gapStart = 0;
double minGapUp = -1, minGapDown = -1;

std::string card;
bool cardPresent = true, filePresent = true;
long failAt = -1, served = 0;

std::vector<std::pair<uint64_t, std::string>> serial;
std::string serialLine;
std::string rows[8];
int beepEdges = 0;
std::vector<uint64_t> keyPresses;

void advance(uint64_t us) { now += us; }

void flushSerial() {
  serial.push_back(std::make_pair(now, serialLine));
  serialLine.clear();
}

void recordStep(Motor& motor) {
  uint8_t pattern = 0;
  for (int i = 0; i < 4; ++i) pattern |= (pins[motor.pins[i]] ? 1 : 0) << i;
  if (pattern && pattern != motor.pattern) {
    ++motor.steps;
    motor.lastStep = now;
    if (gapPending) {
      double gap = (now - gapStart) / 1000.0;
      double& minimum = gapAngle == PICASSO_PEN_UP_DEGREES ? minGapUp : minGapDown;
      if (minimum < 0 || gap < minimum) minimum = gap;
      gapPending = false;
    }
  }
  motor.pattern = pattern;
}

}  // namespace sim

// ------------------------------------------------------------ Arduino API
HardwareSerial Serial;
SDClass SD;
const uint8_t u8x8_font_amstrad_cpc_extended_r[] = {0};

unsigned long millis() { return static_cast<unsigned long>(sim::now / 1000); }
unsigned long micros() { return static_cast<unsigned long>(sim::now); }
void delay(unsigned long ms) { sim::advance(static_cast<uint64_t>(ms) * 1000); }
void delayMicroseconds(unsigned int us) { sim::advance(us); }
void pinMode(uint8_t, uint8_t) {}

void digitalWrite(uint8_t pin, uint8_t value) {
  if (pin == A2 && (sim::pins[pin] != 0) != (value != 0)) ++sim::beepEdges;
  sim::pins[pin] = value;
  for (sim::Motor& motor : sim::motors) {
    if (pin == motor.pins[3]) sim::recordStep(motor);  // TinyStepper writes IN4 last
  }
}

int analogRead(uint8_t pin) {
  sim::advance(sim::kAnalogReadUs);
  return pin == A1 ? sim::keypad : 0;
}

void HardwareSerial::begin(unsigned long) {}
void HardwareSerial::print(const char* text) { sim::serialLine += text; }
void HardwareSerial::print(const __FlashStringHelper* text) { sim::serialLine += reinterpret_cast<const char*>(text); }
void HardwareSerial::print(unsigned long value) { sim::serialLine += std::to_string(value); }
void HardwareSerial::print(unsigned int value) { sim::serialLine += std::to_string(value); }
void HardwareSerial::print(int value) { sim::serialLine += std::to_string(value); }
void HardwareSerial::println(const char* text) { print(text); sim::flushSerial(); }
void HardwareSerial::println(const __FlashStringHelper* text) { print(text); sim::flushSerial(); }
void HardwareSerial::println() { sim::flushSerial(); }

uint8_t Servo::attach(int) { return 0; }
void Servo::write(int angle) {
  sim::servoWrites.push_back(std::make_pair(sim::now, angle));
  sim::gapPending = true;
  sim::gapAngle = angle;
  sim::gapStart = sim::now;
}

bool SDClass::begin(uint8_t) { return sim::cardPresent; }
void SDClass::end() {}
File SDClass::open(const char* path, uint8_t) {
  File file;
  file.open_ = sim::cardPresent && sim::filePresent && strcmp(path, "main.nc") == 0;
  return file;
}

int File::read() {
  if (!open_ || position_ >= sim::card.size()) return -1;
  if (sim::failAt >= 0 && sim::served >= sim::failAt) return -1;  // card removed
  ++sim::served;
  return static_cast<uint8_t>(sim::card[position_++]);
}
int File::available() { return open_ ? static_cast<int>(sim::card.size() - position_) : 0; }
bool File::seek(uint32_t position) {
  if (!open_ || position > sim::card.size()) return false;
  position_ = position;
  return true;
}
uint32_t File::size() { return open_ ? static_cast<uint32_t>(sim::card.size()) : 0; }
void File::close() { open_ = false; }

void U8X8_SSD1306_128X64_NONAME_HW_I2C::begin() {}
void U8X8_SSD1306_128X64_NONAME_HW_I2C::setFont(const uint8_t*) {}
void U8X8_SSD1306_128X64_NONAME_HW_I2C::clear() {
  for (std::string& row : sim::rows) row.clear();
  sim::advance(sim::kDisplayClearUs);
}
void U8X8_SSD1306_128X64_NONAME_HW_I2C::drawString(uint8_t column, uint8_t row, const char* text) {
  draw1x2String(column, row, text);
}
void U8X8_SSD1306_128X64_NONAME_HW_I2C::draw1x2String(uint8_t column, uint8_t row, const char* text) {
  std::string& line = sim::rows[row & 7];
  if (line.size() < column) line.resize(column, ' ');
  line.replace(column, std::string::npos, text);
  sim::advance(sim::kDisplayCharUs * strlen(text));
}

// The sketch itself, compiled as ordinary C++ in this translation unit.
#include "WallDrawingMachine.ino"

// -------------------------------------------------------------- scenarios
static const char* modeName() {
  static const char* const names[] = {"main", "setup", "info", "confirm", "jog", "pen_test",
                                      "message", "validating", "ready", "executing", "result"};
  return names[mode];
}

static const char* phaseName() {
  static const char* const names[] = {"fetch", "settle", "move", "pausing", "paused", "resuming", "ending"};
  return names[phase];
}

static bool reached(const std::string& state) {
  if (state == "paused") return mode == MODE_EXECUTING && phase == EX_PAUSED;
  if (state == "jog_idle") return mode == MODE_JOG && jogRemaining == 0;
  return state == modeName();
}

static void step() {
  loop();
  sim::advance(sim::kLoopCostUs);
}

static void run(uint64_t ms) {
  uint64_t end = sim::now + ms * 1000;
  while (sim::now < end) step();
}

static std::string quoted(const std::string& text) {
  std::string out = "\"";
  for (char ch : text) {
    if (ch == '"' || ch == '\\') out += '\\';
    out += ch;
  }
  return out + "\"";
}

static void report(bool timedOut) {
  char text[16];
  reasonString(text, sizeof(text));
  std::ostringstream json;
  json.precision(9);
  json << "{\"time_ms\":" << sim::now / 1000.0 << ",\"timed_out\":" << (timedOut ? "true" : "false")
       << ",\"mode\":" << quoted(modeName()) << ",\"phase\":" << quoted(phaseName())
       << ",\"outcome\":" << quoted(outcome == OUTCOME_COMPLETED ? "completed" : outcome == OUTCOME_ABORTED ? "aborted" : "failed")
       << ",\"reason\":" << quoted(text) << ",\"failed_line\":" << failedLine
       << ",\"motion_started\":" << (motionStarted ? "true" : "false")
       << ",\"origin_valid\":" << (originValid ? "true" : "false") << ",\"origin_fresh\":" << (originFresh ? "true" : "false")
       << ",\"position\":[" << posX << "," << posY << "],\"rope\":[" << rope1 << "," << rope2 << "]"
       << ",\"motor_positions\":[" << m1.getCurrentPositionInSteps() << "," << m2.getCurrentPositionInSteps() << "]"
       << ",\"steps\":[" << sim::motors[0].steps << "," << sim::motors[1].steps << "]"
       << ",\"last_step_ms\":[" << sim::motors[0].lastStep / 1000.0 << "," << sim::motors[1].lastStep / 1000.0 << "]"
       << ",\"coils_energized\":[" << (sim::motors[0].pattern ? "true" : "false") << "," << (sim::motors[1].pattern ? "true" : "false") << "]"
       << ",\"pen_down\":" << (penDown ? "true" : "false")
       << ",\"min_gap_after_pen_up_ms\":" << sim::minGapUp << ",\"min_gap_after_pen_down_ms\":" << sim::minGapDown
       << ",\"validated\":{\"crc\":" << validatedCrc << ",\"lines\":" << validatedLines << ",\"moves\":" << validatedMoves << "}"
       << ",\"beep_edges\":" << sim::beepEdges << ",\"bytes_served\":" << sim::served;
  json << ",\"key_presses_ms\":[";
  for (size_t i = 0; i < sim::keyPresses.size(); ++i) json << (i ? "," : "") << sim::keyPresses[i] / 1000.0;
  json << "],\"servo_writes\":[";
  for (size_t i = 0; i < sim::servoWrites.size(); ++i) {
    json << (i ? "," : "") << "[" << sim::servoWrites[i].first / 1000.0 << "," << sim::servoWrites[i].second << "]";
  }
  json << "],\"display\":[";
  for (int row = 0; row < 4; ++row) json << (row ? "," : "") << quoted(sim::rows[row * 2]);
  json << "],\"serial\":[";
  for (size_t i = 0; i < sim::serial.size(); ++i) {
    json << (i ? "," : "") << "[" << sim::serial[i].first / 1000.0 << "," << quoted(sim::serial[i].second) << "]";
  }
  json << "]}";
  std::cout << json.str() << std::endl;
}

static int keyValue(const std::string& name) {
  if (name == "down") return PICASSO_KEY_DOWN_ADC;
  if (name == "enter") return PICASSO_KEY_ENTER_ADC;
  if (name == "esc") return PICASSO_KEY_ESC_ADC;
  std::cerr << "unknown key " << name << std::endl;
  std::exit(2);
}

int main() {
  std::string line;
  int status = 0;
  while (std::getline(std::cin, line)) {
    std::istringstream words(line);
    std::string command;
    if (!(words >> command) || command[0] == '#') continue;
    if (command == "card") {
      std::string path;
      words >> path;
      std::ifstream file(path, std::ios::binary);
      if (!file) {
        std::cerr << "cannot read " << path << std::endl;
        return 2;
      }
      sim::card.assign(std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());
      sim::cardPresent = sim::filePresent = true;
    } else if (command == "nocard") {
      sim::cardPresent = false;
    } else if (command == "nofile") {
      sim::filePresent = false;
    } else if (command == "fail_after") {
      long bytes;
      words >> bytes;
      sim::failAt = sim::served + bytes;
    } else if (command == "boot") {
      setup();
    } else if (command == "key") {
      // A person holds the key until the firmware registers it, then releases
      // until the release is registered, each for at least 60 ms.
      std::string name;
      words >> name;
      sim::keyPresses.push_back(sim::now);
      sim::keypad = keyValue(name);
      run(60);
      for (uint64_t end = sim::now + 2000000; keyStable == KEY_NONE && sim::now < end;) step();
      sim::keypad = 1023;
      run(60);
      for (uint64_t end = sim::now + 2000000; keyStable != KEY_NONE && sim::now < end;) step();
    } else if (command == "wait") {
      uint64_t ms;
      words >> ms;
      run(ms);
    } else if (command == "until") {
      std::string state;
      uint64_t ms;
      words >> state >> ms;
      uint64_t end = sim::now + ms * 1000;
      while (!reached(state) && sim::now < end) step();
      if (!reached(state)) {
        report(true);
        return 3;
      }
    } else if (command == "report") {
      report(false);
    } else {
      std::cerr << "unknown command " << command << std::endl;
      return 2;
    }
  }
  return status;
}
